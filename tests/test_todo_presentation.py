"""Production B: web presentation state must not change task semantics."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from chatsite.todo_state import WebState, StateError
from test_todo_web import environment, login, new_board


def test_presentation_defaults_persist_and_do_not_cross_scopes(tmp_path):
    state=WebState(tmp_path/'web.sqlite3')
    assert state.presentation('one','a')=={'layout':'logicalStructure','revision':0}
    saved=state.save_presentation('one','a','mindMap',0)
    assert saved=={'layout':'mindMap','revision':1}
    assert WebState(state.path).presentation('one','a')==saved
    assert state.presentation('one','b')['revision']==0
    assert state.presentation('two','a')['revision']==0
    assert state.save_presentation('one','a','mindMap',1)==saved
    state.delete_board_state('one','a')
    assert state.presentation('one','a')['revision']==0


@pytest.mark.parametrize('layout',['unknown','<script>',None,True,3,{'layout':'mindMap'}])
def test_presentation_rejects_unknown_or_non_string_layout(tmp_path,layout):
    state=WebState(tmp_path/'web.sqlite3')
    with pytest.raises(StateError):state.save_presentation('one','a',layout,0)
    assert state.presentation('one','a')['revision']==0


@pytest.mark.parametrize('revision',[True,-1,'0',None,0.5])
def test_presentation_rejects_bad_revision(tmp_path,revision):
    state=WebState(tmp_path/'web.sqlite3')
    with pytest.raises(StateError):state.save_presentation('one','a','mindMap',revision)


def test_presentation_cas_has_one_concurrent_winner(tmp_path):
    state=WebState(tmp_path/'web.sqlite3')
    def save(layout):
        try:return state.save_presentation('one','a',layout,0)
        except StateError as exc:return exc.status
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(save,['mindMap','timeline']))
    assert sum(isinstance(r,dict) for r in results)==1
    assert 409 in results
    assert state.presentation('one','a')['revision']==1


def test_presentation_api_auth_cas_export_import_and_cleanup(tmp_path):
    app,c=environment(tmp_path)
    assert c.get('/api/boards/missing/presentation').status_code==401
    login(c);board=new_board(c);path='/api/boards/'+board['id']+'/presentation'
    before=c.get('/api/boards/'+board['id']).json()['board']
    assert c.get(path).json()=={'layout':'logicalStructure','revision':0}
    assert c.patch(path,json={'layout':'mindMap','revision':0},headers={'X-CSRF-Token':'wrong'}).status_code==403
    assert c.patch(path,json={'layout':'mindMap','revision':0,'secret':'no'}).status_code==400
    assert c.patch(path,json={'layout':'mindMap','revision':0}).json()=={'layout':'mindMap','revision':1}
    assert c.patch(path,json={'layout':'timeline','revision':0}).status_code==409
    assert c.get('/api/boards/'+board['id']).json()['board']==before
    exported=c.get('/api/boards/'+board['id']+'/export').json()
    assert exported['presentation']=={'layout':'mindMap','revision':1}
    imported=c.post('/api/import',json={'board':exported})
    assert imported.status_code==200
    other=imported.json()['board']['id']
    assert other!=board['id'] and c.get('/api/boards/'+other+'/presentation').json()['layout']=='mindMap'
    count=len(c.get('/api/boards').json()['boards'])
    for value in ({'layout':'bad'}, {'layout':'mindMap','extra':True}, False):
        assert c.post('/api/import',json={'board':{**exported,'presentation':value}}).status_code==400
    assert len(c.get('/api/boards').json()['boards'])==count
    assert c.request('DELETE','/api/boards/'+board['id'],json={'revision':board['revision'],'confirm':True}).status_code==200
    assert c.get(path).status_code==404
    with app.state.web_state.connection() as db:
        assert db.execute('SELECT count(*) FROM presentations WHERE board_id=?',(board['id'],)).fetchone()[0]==0


def test_presentation_cannot_access_another_owner_board(tmp_path):
    app,c=environment(tmp_path);login(c)
    board=app.state.boards.create('other@example.test')
    path='/api/boards/'+board['id']+'/presentation'
    assert c.get(path).status_code==404
    assert c.patch(path,json={'layout':'timeline','revision':0}).status_code==404
