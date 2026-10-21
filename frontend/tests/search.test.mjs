import test from 'node:test';
import assert from 'node:assert/strict';
import { findBookmarks, isUrl, parseQuery, suggestionProvider, webUrl } from '../src/lib/search.js';
const tabs = [{ name:'Home', categories:[{ name:'Tools', links:[{id:'1',name:'Docker docs',url:'https://docs.docker.com'}, {id:'2',name:'My NAS',url:'http://192.168.1.8:5000'}] }] },{name:'Work',categories:[{name:'Servers',links:[{id:'3',name:'Docker',url:'https://work.example.test'},{id:'4',name:'서버 관리',url:'http://server.local'}]}]}];
const engines={g:['https://www.google.com/search?q=','Google'],d:['https://duckduckgo.com/?q=','DuckDuckGo']};
test('name match spans tabs and exact names rank first',()=>assert.deepEqual(findBookmarks(tabs,'DOCKER').map(item=>item.id),['3','1']));
test('URL, private IP, tab/category context and all query terms are searchable',()=>{
 assert.equal(findBookmarks(tabs,'192.168.1.8')[0].id,'2');
 assert.equal(findBookmarks(tabs,'work docker')[0].id,'3');
 assert.equal(findBookmarks(tabs,'서버')[0].id,'4');
 assert.equal(findBookmarks(tabs,'does not exist').length,0);
});
test('engine shortcuts preserve input and encode web search values',()=>{
 assert.deepEqual(parseQuery(' !g docker compose ',engines,'d'),{query:'docker compose',engine:'g',explicit:true});
 assert.deepEqual(parseQuery('!unknown value',engines,'d'),{query:'!unknown value',engine:'d',explicit:false});
 assert.equal(webUrl(engines,'g','가나다 & x'),'https://www.google.com/search?q=%EA%B0%80%EB%82%98%EB%8B%A4%20%26%20x');
});
test('direct address handling only recognizes supported URL shapes',()=>{
 for(const value of ['https://nas.local','192.168.1.8:5000','localhost:8090','example.com']) assert.equal(isUrl(value),true,value);
 for(const value of ['javascript:alert(1)','docker compose','일반 검색어']) assert.equal(isUrl(value),false,value);
});

test('suggestions follow default and explicit engine, with no fallback for unsupported engines', () => {
 const providers = { ...engines, y: ['https://yandex.com/search/?text=', 'Yandex'], p: ['https://www.perplexity.ai/search/?q=', 'Perplexity'] };
 for (const selected of ['g', 'd', 'y', 'p']) {
  const normal = parseQuery('한글 검색', providers, selected);
  assert.equal(suggestionProvider(normal.engine), selected === 'p' ? null : selected);
  const shortcut = parseQuery(`!${selected} 한글 검색`, providers, 'd');
  assert.equal(shortcut.query, '한글 검색');
  assert.equal(suggestionProvider(shortcut.engine), selected === 'p' ? null : selected);
 }
 assert.equal(suggestionProvider('unknown'), null);
});
