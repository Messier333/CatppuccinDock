import base64,time,unittest
from io import BytesIO
from PIL import Image
from fastapi.testclient import TestClient
import test_auth as legacy
from test_auth import HEADERS
from app.db.models import SharedLink, TrashItem
from app.db.session import SessionLocal
from app.main import app

class Operations(unittest.TestCase):
    setUp=legacy.AuthenticationTests.setUp
    tearDown=legacy.AuthenticationTests.tearDown
    setup_owner=legacy.AuthenticationTests.setup_owner
    def member(self,name='member'):
        r=self.client.post('/api/admin/users',json={'username':name,'password':'a-member-password'},headers=HEADERS)
        self.assertEqual(r.status_code,200,r.text)
        client=TestClient(app);client.post('/api/auth/login',json={'username':name,'password':'a-member-password'},headers=HEADERS)
        return client,r.json()['id']
    def preview(self,doc,password=''):
        r=self.client.post('/api/backups/import-preview',json={'document':doc,'password':password},headers=HEADERS)
        self.assertEqual(r.status_code,200,r.text);return r.json()
    def test_encrypted_roundtrip_wrong_password_tamper_and_owned_preview(self):
        self.setup_owner()
        gif=BytesIO();Image.new('RGB',(2,2),'red').save(gif,format='GIF')
        image=self.client.post('/api/backgrounds',content=gif.getvalue(),headers=HEADERS|{'Content-Type':'image/gif'}).json()
        tab=self.client.get('/api/portal').json()['tabs'][0]
        self.client.put('/api/tabs/'+tab['id'],json={'name':tab['name'],'banner':tab['banner'],'background_id':image['id']},headers=HEADERS)
        exported=self.client.post('/api/backups/export',json={'encrypted':True,'password':'a-backup-password','include_settings':True},headers=HEADERS)
        self.assertEqual(exported.status_code,200,exported.text)
        doc=exported.json();self.assertEqual(doc['format'],'CatppuccinDock.encrypted');self.assertNotIn('raindrop',exported.text)
        self.assertEqual(self.client.post('/api/backups/import-preview',json={'document':doc,'password':'wrong'},headers=HEADERS).status_code,422)
        changed=doc|{'ciphertext':base64.b64encode(b'changed').decode()}
        self.assertEqual(self.client.post('/api/backups/import-preview',json={'document':changed,'password':'a-backup-password'},headers=HEADERS).status_code,422)
        self.assertEqual(self.client.get('/api/portal').json()['tabs'][0]['id'],tab['id'])
        p=self.preview(doc,'a-backup-password');self.assertEqual(p['images'],1)
        other,_=self.member()
        self.assertEqual(other.post('/api/backups/import',json={'preview_id':p['preview_id'],'mode':'replace'},headers=HEADERS).status_code,409)
        result=self.client.post('/api/backups/import',json={'preview_id':p['preview_id'],'mode':'replace','apply_settings':True},headers=HEADERS)
        self.assertEqual(result.status_code,200,result.text);self.assertEqual(result.json()['added'],34)
        fresh=self.client.get('/api/portal').json()
        self.assertEqual(fresh['tabs'][0]['background_id'],image['id'])
        undo=result.json()['undo_id'];self.assertEqual(self.client.post('/api/trash/'+undo+'/restore',headers=HEADERS).status_code,200)
        self.assertEqual(self.client.get('/api/portal').json()['tabs'][0]['id'],tab['id'])
        self.assertEqual(self.client.post('/api/backups/import',json={'preview_id':p['preview_id']},headers=HEADERS).status_code,409)
    def test_merge_duplicate_preview_stale_and_no_settings_privilege_escalation(self):
        self.setup_owner()
        doc=self.client.post('/api/backups/export',json={'include_images':False},headers=HEADERS).json()
        p=self.preview(doc);self.assertEqual(p['duplicates'],34)
        result=self.client.post('/api/backups/import',json={'preview_id':p['preview_id']},headers=HEADERS)
        self.assertEqual(result.json()['duplicates'],34)
        p=self.preview(doc)
        tab=self.client.get('/api/portal').json()['tabs'][0]
        self.client.post('/api/bookmarks',json={'category_id':tab['categories'][0]['id'],'name':'New','url':'https://new.test'},headers=HEADERS)
        self.assertEqual(self.client.post('/api/backups/import',json={'preview_id':p['preview_id']},headers=HEADERS).status_code,409)
        member,_=self.member()
        self.assertEqual(member.post('/api/backups/export',json={'include_settings':True},headers=HEADERS).status_code,403)
        global_doc=self.client.post('/api/backups/export',json={'include_settings':True},headers=HEADERS).json()
        p=member.post('/api/backups/import-preview',json={'document':global_doc},headers=HEADERS).json()
        self.assertEqual(member.post('/api/backups/import',json={'preview_id':p['preview_id'],'apply_settings':True},headers=HEADERS).status_code,403)
    def test_trash_hierarchy_last_tab_ownership_expiry_and_order_conflict(self):
        self.setup_owner();member,_=self.member()
        portal=self.client.get('/api/portal').json();tab=portal['tabs'][0];cat=tab['categories'][0];link=cat['links'][0]
        result=self.client.delete('/api/tabs/'+tab['id'],headers=HEADERS);self.assertEqual(result.status_code,200,result.text)
        trash_id=result.json()['trash_id'];self.assertEqual(self.client.get('/api/bookmarks/'+link['id']).status_code,404)
        self.assertEqual(member.post('/api/trash/'+trash_id+'/restore',headers=HEADERS).status_code,404)
        self.assertEqual(self.client.post('/api/trash/'+trash_id+'/restore',headers=HEADERS).status_code,200)
        self.assertEqual(self.client.get('/api/bookmarks/'+link['id']).status_code,200)
        ids=[row['id'] for row in cat['links']]
        order=self.client.post('/api/reorder',json={'kind':'bookmarks','parent_id':cat['id'],'ids':ids[::-1]},headers=HEADERS).json()
        self.assertEqual(self.client.post('/api/trash/'+order['undo_id']+'/restore',headers=HEADERS).status_code,200)
        order=self.client.post('/api/reorder',json={'kind':'bookmarks','parent_id':cat['id'],'ids':ids[::-1]},headers=HEADERS).json()
        self.client.post('/api/bookmarks',json={'name':'New','url':'https://new.test','category_id':cat['id']},headers=HEADERS)
        self.assertEqual(self.client.post('/api/trash/'+order['undo_id']+'/restore',headers=HEADERS).status_code,409)
        deleted=self.client.delete('/api/bookmarks/'+link['id'],headers=HEADERS).json()['trash_id']
        with SessionLocal.begin() as db:db.get(TrashItem,deleted).expires_at=time.time()-1
        self.assertEqual(self.client.post('/api/trash/'+deleted+'/restore',headers=HEADERS).status_code,404)
    def test_browser_html_selected_import_unsafe_urls_duplicates_and_export_escaping(self):
        self.setup_owner()
        html='<!DOCTYPE NETSCAPE-Bookmark-file-1><DL><p><DT><H3>Tools &amp; More</H3><DL><p><DT><A HREF="https://a.test">A &amp; B</A><DT><A HREF="javascript:alert(1)">Bad</A><DT><A HREF="https://a.test">Duplicate</A><DT><A HREF="https://b.test">B</A></DL></DL>'
        p=self.client.post('/api/browser-bookmarks/preview',json={'html':html},headers=HEADERS)
        self.assertEqual(p.status_code,200,p.text);p=p.json();self.assertEqual(p['skipped'],1);self.assertEqual(p['duplicates'],1)
        result=self.client.post('/api/browser-bookmarks/import',json={'preview_id':p['preview_id'],'selected_ids':['0']},headers=HEADERS)
        self.assertEqual(result.status_code,200,result.text);self.assertEqual(result.json()['added'],1)
        exported=self.client.get('/api/browser-bookmarks/export')
        self.assertIn('A &amp; B',exported.text);self.assertNotIn('javascript:',exported.text)
        self.assertIn('attachment',exported.headers['content-disposition'])
    def test_restricted_links_enforced_on_all_routes_and_backup_restore(self):
        self.setup_owner();member,uid=self.member();other,otherid=self.member('other')
        with SessionLocal.begin() as db:
            link=SharedLink(name='Restricted',url='https://restricted.test/',source_name='Fixture',published=True)
            db.add(link);db.flush();lid=link.id
        group=self.client.post('/api/admin/groups',json={'name':'Family','user_ids':[uid]},headers=HEADERS).json()
        payload={'name':'Restricted','icon':'world','published':True,'access_mode':'restricted','user_ids':[],'group_ids':[group['id']]}
        r=self.client.put('/api/admin/library/'+lid,json=payload,headers=HEADERS);self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(len(member.get('/api/library').json()),1);self.assertEqual(other.get('/api/library').json(),[])
        category=member.get('/api/portal').json()['tabs'][0]['categories'][0]
        result=member.post('/api/library/'+lid+'/add',json={'category_id':category['id']},headers=HEADERS).json();bid=result['id']
        doc=member.post('/api/backups/export',json={},headers=HEADERS).json()
        self.client.put('/api/admin/groups/'+group['id'],json={'name':'Family','user_ids':[]},headers=HEADERS)
        self.assertEqual(member.get('/api/bookmarks/'+bid).status_code,404)
        self.assertEqual(member.get('/api/library').json(),[])
        self.assertNotIn(bid,[l['id'] for t in member.get('/api/portal').json()['tabs'] for c in t['categories'] for l in c['links']])
        p=member.post('/api/backups/import-preview',json={'document':doc},headers=HEADERS).json();self.assertEqual(p['restricted'],1)
        result=member.post('/api/backups/import',json={'preview_id':p['preview_id'],'mode':'replace'},headers=HEADERS)
        self.assertEqual(result.status_code,200,result.text);self.assertEqual(result.json()['restricted'],1)
        # Older clients changing only the name must not reset a restricted ACL.
        self.client.put('/api/admin/library/'+lid,json={'name':'Renamed','published':True},headers=HEADERS)
        self.assertEqual(other.get('/api/library').json(),[])
        self.assertEqual(member.get('/api/admin/groups').status_code,403)
