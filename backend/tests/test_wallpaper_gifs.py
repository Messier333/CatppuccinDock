import unittest
from unittest.mock import patch

from app.schemas.backgrounds import BackgroundImport, BackgroundSource
from app.services.media import gif_search, wallpaper_gifs
from app.services.media.remote_media import RemoteMediaError

ALPHA = '''<div itemscope itemtype="http://schema.org/ImageObject" itemprop="associatedMedia">
<meta itemprop="contentUrl" content="https://giffiles.alphacoders.com/209/209343.gif">
<meta itemprop="name" content="Pixel Train &amp; Sunrise"><meta itemprop="author" content="Artist">
<meta itemprop="thumbnailUrl" content="https://giffiles.alphacoders.com/209/thumb-209343.jpg">
<meta itemprop="width" content="1280"><meta itemprop="height" content="620"><meta itemprop="fileFormat" content="gif">
<div><a href="https://example.org"><img src="preview.jpg"></a></div></div>'''
MOTION = '''<h1>Pixel Gif Wallpapers</h1><div><picture><source type=image/webp srcset=/media/43/pixel-koi-pond_312.webp>
<img src=/media/43/pixel-koi-pond_312.gif alt="Pixel Koi Pond gif preview"></picture>
<a class=gf_ttl href=/pixel-koi-pond>Pixel Koi Pond Gif Wallpaper</a><a href=/pixel-koi-pond#download_gif>GIF</a></div>
<a href="/gifs:pixel/2/">Next</a>'''


class WallpaperGifTests(unittest.TestCase):
    def setUp(self):
        gif_search.cache.clear()

    def test_alpha_structured_metadata_and_nested_markup(self):
        rows = wallpaper_gifs.alpha_items(ALPHA)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['id'], '209343')
        self.assertEqual(rows[0]['title'], 'Pixel Train & Sunrise')
        self.assertEqual(rows[0]['source']['author'], 'Artist')
        self.assertEqual(rows[0]['source']['provider'], 'alphacoders')
        self.assertEqual(rows[0]['width'], 1280)
        self.assertEqual(rows[0]['url'], 'https://giffiles.alphacoders.com/209/209343.gif')

    def test_alpha_ignores_non_gifs_untrusted_hosts_and_deduplicates(self):
        self.assertEqual(wallpaper_gifs.alpha_items(ALPHA+ALPHA), wallpaper_gifs.alpha_items(ALPHA))
        self.assertEqual(wallpaper_gifs.alpha_items(ALPHA.replace('giffiles.alphacoders.com', 'localhost')), [])
        self.assertEqual(wallpaper_gifs.alpha_items(ALPHA.replace('209343.gif', '209343.mp4')), [])
        self.assertEqual(wallpaper_gifs.alpha_items(ALPHA.replace('https://giffiles', 'http://giffiles')), [])

    def test_alpha_search_translates_queries_paginates_and_caches(self):
        with patch('app.services.media.wallpaper_gifs.page_html', return_value='<link rel="canonical" href="https://alphacoders.com/city-gifs">'+ALPHA*15) as request:
            result = gif_search.search('alphacoders', '도시 풍경', 2)
            self.assertIn('q=city+landscape', request.call_args_list[0].args[0])
            self.assertIn('page=2', request.call_args.args[0])
            self.assertIn('type=gif', request.call_args_list[0].args[0])
            self.assertTrue(request.call_args.args[0].startswith('https://alphacoders.com/city-gifs?'))
            self.assertNotIn('url', result['items'][0])
            self.assertTrue(result['has_more'])
            self.assertEqual(gif_search.search('alphacoders', '도시 풍경', 2), result)
            self.assertEqual(request.call_count, 2)

    def test_alpha_resolution_uses_verified_id_not_another_related_image(self):
        related = ALPHA.replace('209343', '111111')
        with patch('app.services.media.wallpaper_gifs.page_html', return_value=related+ALPHA) as page, \
                patch('app.services.media.gif_search.fetch_public', return_value=b'GIF89a;') as download:
            data, title, source = gif_search.download('alphacoders', '209343')
            self.assertEqual(data, b'GIF89a;')
            self.assertEqual(source['item_id'], '209343')
            self.assertEqual(page.call_args.args[0], 'https://gifs.alphacoders.com/gifs/view/209343')
            self.assertEqual(download.call_args.args[0], 'https://giffiles.alphacoders.com/209/209343.gif')

    def test_motion_categories_preview_and_next_page(self):
        with patch('app.services.media.wallpaper_gifs.page_html', return_value=MOTION) as request:
            result = wallpaper_gifs.search('motionbgs', '픽셀', 1)
            self.assertEqual(request.call_args.args[0], 'https://motionbgs.com/gifs:pixel/')
            self.assertEqual(result['items'][0]['id'], 'pixel-koi-pond')
            self.assertEqual(result['items'][0]['title'], 'Pixel Koi Pond')
            self.assertEqual(result['items'][0]['preview_url'], 'https://motionbgs.com/media/43/pixel-koi-pond_312.webp')
            self.assertTrue(result['has_more'])
            wallpaper_gifs.search('motionbgs', '자연', 2)
            self.assertEqual(request.call_args.args[0], 'https://motionbgs.com/gifs:nature/2/')

    def test_motion_resolves_offered_gif_download_from_own_detail_page(self):
        html = '<h1>Pixel Koi Pond Live Wallpaper</h1><a href="https://evil.test/dl/gif/9">skip</a><a href=/dl/gif/43>Download GIF</a>'
        with patch('app.services.media.wallpaper_gifs.page_html', return_value=html) as request:
            item = wallpaper_gifs.resolve('motionbgs', 'pixel-koi-pond')
            self.assertEqual(item['url'], 'https://motionbgs.com/dl/gif/43')
            self.assertEqual(item['source']['title'], 'Pixel Koi Pond')
            self.assertEqual(request.call_args.args[0], 'https://motionbgs.com/pixel-koi-pond')
        with patch('app.services.media.wallpaper_gifs.page_html', return_value='<h1>No GIF</h1>'):
            with self.assertRaises(RemoteMediaError) as error:
                wallpaper_gifs.resolve('motionbgs', 'no-gif')
            self.assertEqual(error.exception.status, 422)

    def test_unknown_motion_topic_is_empty_and_host_failures_are_reported(self):
        with patch('app.services.media.wallpaper_gifs.page_html', side_effect=RemoteMediaError('missing', 404)):
            self.assertEqual(wallpaper_gifs.search('motionbgs', 'unknown topic', 1)['items'], [])
        with patch('app.services.media.wallpaper_gifs.page_html', side_effect=RemoteMediaError('limited', 429)):
            with self.assertRaises(RemoteMediaError):
                wallpaper_gifs.search('motionbgs', 'nature', 1)

    def test_unknown_alpha_search_is_empty_but_real_provider_errors_propagate(self):
        with patch('app.services.media.wallpaper_gifs.page_html', side_effect=RemoteMediaError('missing', 404)):
            result = gif_search.search('alphacoders', 'DEV', 1)
            self.assertEqual(result, {'items': [], 'page': 1, 'has_more': False, 'provider': 'alphacoders'})
            with self.assertRaises(RemoteMediaError):
                wallpaper_gifs.resolve('alphacoders', '42')
        with patch('app.services.media.wallpaper_gifs.page_html', side_effect=RemoteMediaError('limited', 429)):
            with self.assertRaises(RemoteMediaError):
                wallpaper_gifs.search('alphacoders', 'DEV', 1)

    def test_provider_identifiers_cannot_turn_into_arbitrary_urls(self):
        with patch('app.services.media.wallpaper_gifs.page_html') as request:
            for provider, identifier in (('alphacoders', '../42'), ('alphacoders', 'https://localhost/'),
                                         ('motionbgs', '../secret'), ('motionbgs', 'https://localhost/'), ('motionbgs', 'a'*161)):
                with self.assertRaises(RemoteMediaError):
                    wallpaper_gifs.resolve(provider, identifier)
            request.assert_not_called()
        for provider in ('alphacoders', 'motionbgs', 'commons', 'openverse'):
            self.assertEqual(BackgroundImport(provider=provider, item_id='42').provider, provider)
