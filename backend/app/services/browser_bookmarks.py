"""Read Netscape browser bookmark exports without rendering their HTML."""
from html.parser import HTMLParser
from pydantic import HttpUrl
from fastapi import HTTPException

class BrowserBookmarks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.folders=[];self.frames=[];self.pending=None;self.capture=None;self.text=[];self.href=None;self.rows=[];self.skipped=0
    def handle_starttag(self, tag, attrs):
        tag=tag.lower()
        if tag=='dl':
            if len(self.frames)>=20:raise HTTPException(422,'폴더 단계가 너무 깊습니다.')
            pushed=self.pending is not None
            self.frames.append(pushed)
            if pushed:self.folders.append(self.pending)
            self.pending=None
        elif tag in ('h3','a'):
            self.capture=tag;self.text=[];self.href=dict(attrs).get('href') if tag=='a' else None
    def handle_data(self, data):
        if self.capture and sum(map(len,self.text))<2048:self.text.append(data[:2048])
    def handle_endtag(self, tag):
        tag=tag.lower()
        if tag=='dl' and self.frames:
            if self.frames.pop():self.folders.pop()
        if tag!=self.capture:return
        title=' '.join(''.join(self.text).split())
        if tag=='h3':self.pending=title[:80] or '이름 없는 폴더'
        elif tag=='a':
            try:
                url=HttpUrl(self.href)
                if url.username or url.password or len(str(url))>2048:raise ValueError('Invalid URL')
                self.rows.append({'name':title[:120] or url.host,'url':str(url),'folders':list(self.folders)})
                if len(self.rows)>10000:raise HTTPException(422,'한 번에 최대 10,000개 북마크를 가져올 수 있습니다.')
            except (ValueError,TypeError):self.skipped+=1
        self.capture=None;self.text=[]

def parse_bookmarks(text):
    if len(text.encode('utf-8'))>5*1024*1024:raise HTTPException(413,'브라우저 북마크는 최대 5MB입니다.')
    parser=BrowserBookmarks()
    try:parser.feed(text);parser.close()
    except (ValueError,RecursionError) as error:raise HTTPException(422,'북마크 HTML을 읽을 수 없습니다.') from error
    if not parser.rows:raise HTTPException(422,'가져올 HTTP/HTTPS 북마크가 없습니다.')
    # Preserve every folder path as a category under one import tab.
    categories={}
    for row in parser.rows:
        path=' / '.join(row['folders'])[:80] or '기본'
        categories.setdefault(path,[]).append({'name':row['name'],'url':row['url'],'icon':'world','icon_color':'auto'})
    if len(categories)>500:raise HTTPException(422,'한 번에 최대 500개 폴더를 가져올 수 있습니다.')
    return {'format':'CatppuccinDock','version':1,'tabs':[{'name':'브라우저 북마크','banner':'none','background_key':None,
        'categories':[{'name':name,'links':links} for name,links in categories.items()]}],'images':[],'settings':None},parser.skipped
