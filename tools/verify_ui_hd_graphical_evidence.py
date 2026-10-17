"""Validate saved owned A/B HD-font/icon observations without opening processes.

Inputs are immutable evidence files. The tool performs no UI operations,
debugger attachment, native calls, socket queries or remote requests. Screenshots
are identified by file hashes; visual assessment belongs to the human operator.
"""
from __future__ import annotations
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from deploy import client_ui_hd_fonts as fonts
from deploy import client_ui_hd_icons as icons

FONT_PROOF=ROOT/'reports/ui-hd-assets/native-fonts/native-unicode-loader-proof.json'
DEFAULT_CANDIDATE=ROOT/'reports/ui-hd-assets/client/silver.dll'

def require(value,message):
    if not value:raise ValueError(message)
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read_json(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def identity(path):
    p=Path(path).resolve();return {'path':str(p),'sha256':digest(p),'bytes':p.stat().st_size}
def pointer(value):
    require(isinstance(value,str) and re.fullmatch(r'0x[0-9a-fA-F]+',value),'Invalid observed pointer')
    return int(value,16)
def stamp(value):
    result=datetime.fromisoformat(value.replace('Z','+00:00'))
    require(result.tzinfo is not None,'Evidence timestamp lacks timezone')
    return result
def pot(value):return 1<<(value-1).bit_length()
def load_events(path):
    events=[json.loads(line) for line in Path(path).read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    require(events and all(isinstance(e,dict) and 'event' in e and 'utc' in e for e in events),'Malformed native event log')
    times=[stamp(e['utc']) for e in events]
    require(times==sorted(times),'Event timestamps are not monotonic')
    return events

def validate_hd(hd,manifest,*,require_draws=True):
    require(hd.get('observerInstalled') is True,'HD native observer was not installed')
    f=hd['font'];i=hd['icon']
    require(f['loadStatus']==1 and f['error']==0 and f['installStatus']==1,'Font runtime did not load/install cleanly')
    require(f['loadedAtlases']==36 and f['loadFailures']==0 and f['initCount']>=1,'Font atlases are incomplete')
    require(f['fallbacks']==0,'Selected font adaptation used a fallback')
    if require_draws:
        require(f['adaptedGlyphs']>0 and f['snappedVertices']>0,'Actual font adaptation/pixel snapping was not observed')
    require(i['status']==1 and i['loadRows']==15 and i['readyRows']==15 and i['failedRows']==0,'Icon runtime resources are incomplete')
    require(i['fallbacks']==0,'Selected icons used a fallback')
    if require_draws:
        require(i['draws']>0,'Selected icons did not draw cleanly')
    # This diagnostic is assigned on the first adapted icon draw, after its
    # resources have already loaded. A pre-world login screen has no such draw.
    ti_base=pointer(i['nativeTiBase'])
    require(ti_base==0x400000 or (not require_draws and i['draws']==0 and ti_base==0),
            'Observed TI base differs from the pinned executable')
    fr=hd['fontRows'];ir=hd['iconRows']
    require(len(fr)==9 and [(r['index'],r['name']) for r in fr]==list(enumerate(fonts.FONTS)),'Observed native font roles differ')
    require(len(ir)==15 and [r['index'] for r in ir]==list(range(15)),'Observed icon rows differ')
    font_objects=[];font_textures=[];font_gpu=[];icon_textures=[];icon_gpu=[]
    for index,row in enumerate(fr):
        obj=pointer(row['fontObject']);require(obj>0,'Native font object is null');font_objects.append(obj)
        require([t['density'] for t in row['textures']]==list(fonts.PERCENTS),'Font density order differs')
        for texture,asset in zip(row['textures'],manifest['fonts'][index]['density_sets']):
            obj=pointer(texture['object']);gpu=pointer(texture.get('gpu','0x0'))
            require(obj and gpu,'Font atlas native/GPU handle is null')
            require(texture.get('renderTarget')==0,'Font atlas is not a managed PNG texture')
            require((texture['width'],texture['height'])==(asset['width'],asset['height']),'Native font texture allocation dimensions differ from the selected PNG')
            require(pot(asset['width'])==asset['width'] and pot(asset['height'])==asset['height'],'Selected font atlas is not POT')
            font_textures.append(obj);font_gpu.append(gpu)
    require(len(set(font_objects))==9 and len(set(font_textures))==36 and len(set(font_gpu))==36,'Font identities or density atlases alias')
    for index,row in enumerate(ir):
        _,_,lw,lh,_=icons.RESOURCES[index]
        require(pointer(row['originalTexture'])>0 and row['status']==1 and row['fallbacks']==0,'Original icon identity/load/fallback differs')
        require((row['width'],row['height'])==(lw,lh),'Logical icon geometry changed')
        require([t['density'] for t in row['textures']]==list(icons.DENSITIES),'Icon density order differs')
        for texture in row['textures']:
            density=texture['density'];tw=icons.physical(lw,density);th=icons.physical(lh,density)
            obj=pointer(texture['object']);gpu=pointer(texture.get('gpu','0x0'))
            require(obj and gpu and texture.get('renderTarget')==0,'Icon density lacks a live managed GPU texture')
            require((texture['tileWidth'],texture['tileHeight'])==(tw,th),'Icon density tile dimensions differ')
            require((texture['imageWidth'],texture['imageHeight'])==(tw*2,th*2),'Icon density image dimensions differ')
            require((texture['width'],texture['height'])==(pot(tw*2),pot(th*2)),'Icon physical POT texture dimensions differ')
            icon_textures.append(obj);icon_gpu.append(gpu)
    require(len(set(icon_textures))==60 and len(set(icon_gpu))==60,'Icon density textures alias by basename or GPU handle')
    font_samples=[];icon_samples=[]
    for sample in hd['fontSamples']:
        density=sample['density'];s=sample['state'];role=s['lastRole'];cp=s['lastCodepoint']
        require(density in fonts.PERCENTS and 0<=role<9,'Invalid sampled font density/role')
        require(s['lastPercent']==density and s['fallbackReason']==0,'Sample did not adapt the selected density')
        glyph=next((g for g in manifest['fonts'][role]['glyphs'] if g['codepoint']==cp),None)
        require(glyph is not None,'Sampled codepoint is not a selected glyph')
        crop=glyph['source_rects'][fonts.PERCENTS.index(density)]
        require(tuple(s[k] for k in ('sourceX','sourceY','sourceWidth','sourceHeight'))==tuple(crop),'Actual font source crop differs from its density atlas')
        require((s['destinationWidth'],s['destinationHeight'])==tuple(glyph['visual_logical_box'][2:]),'Logical font ink bounds changed')
        require(pointer(s['selectedTexture'])==pointer(fr[role]['textures'][fonts.PERCENTS.index(density)]['object']),'Sampled font texture is not its selected atlas')
        require(s['rotation'] in (0,90,-90),'Unknown font rotation in actual GUI sample')
        font_samples.append({'density':density,'role':fonts.FONTS[role],'codepoint':cp,'source':crop,
                             'destination':[s[k] for k in ('destinationX','destinationY','destinationWidth','destinationHeight')]})
    for sample in hd['iconSamples']:
        density=sample['density'];index=sample['index']
        require(density in icons.DENSITIES and 0<=index<15,'Invalid sampled icon density/index')
        row=ir[index];texture=row['textures'][icons.DENSITIES.index(density)]
        require(pointer(sample['texture'])==pointer(texture['object']),'Sampled icon uses another density texture')
        require((sample['sourceWidth'],sample['sourceHeight'])==(texture['tileWidth'],texture['tileHeight']),'Actual icon crop density differs')
        require(sample['sourceX'] in (0,texture['tileWidth']) and sample['sourceY'] in (0,texture['tileHeight']),'Sampled icon frame is out of its 2x2 source grid')
        require(sample['sourceX']+sample['sourceWidth']<=texture['imageWidth'] and sample['sourceY']+sample['sourceHeight']<=texture['imageHeight'],'Icon source exceeds its PNG')
        require((sample['destinationWidth'],sample['destinationHeight'])==(row['width'],row['height']),'Actual icon destination is not its original logical size')
        icon_samples.append({'density':density,'index':index,'source':[sample[k] for k in ('sourceX','sourceY','sourceWidth','sourceHeight')],
                             'destination':[sample[k] for k in ('destinationX','destinationY','destinationWidth','destinationHeight')]})
    if require_draws:
        require(font_samples and icon_samples,'Actual source/destination draw samples are absent')
    return {'font_roles_loaded':9,'font_density_atlases_loaded':36,'unique_icon_density_textures':60,
        'managed_png_render_target_flags':0,'font_samples':font_samples,'icon_samples':icon_samples,
        'counters':{'font_glyphs':f['adaptedGlyphs'],'font_snapped_vertices':f['snappedVertices'],'icon_draws':i['draws']},
        'font_objects':font_objects,'font_textures':font_textures,'icon_textures':icon_textures}

def validate_run(path,manifest):
    events=load_events(path)
    finals=[e for e in events if e['event']=='screen_qa_final']
    require(len(finals)==1 and finals[0]['failures']==0,'Owned native run has no clean final status')
    final=finals[0];state=final['state'];display=final['display']
    require(state['authenticated'] is True and state['fault'] is None and state['credentialsSubmitted'] is True,'Actual native authentication failed')
    require(all(state[k]==0 for k in ('authChallengeStatus','loginStatus','serverLoginStatus','gameAuth1Status','gameAuth2Status','characterSelectStatus')),'Native authentication or character status is nonzero')
    require(state['charactersLoaded'] is True and state['worldStartSent'] is True and state['selectedCharacter']['id']>0,'Actual character/world start was not observed')
    require(any(e['event']=='native_world_start_builder' and e['character_select_status']==0 for e in events),'Native world-start builder event is absent')
    ready=[e for e in events if e['event']=='screen_qa_ready'];require(len(ready)==1,'Ambiguous owned process identity')
    require(ready[0]['own_process_only'] is True and ready[0]['endpoint_certificates_validated'] is True,'Owned TLS route guards did not pass')
    require(any(e['event']=='production_native_tls_route_verified' and e['route_bytes_verified']==40 for e in events),'Pinned native TLS route was not verified')
    require(display['initialized'] is True and display['presentCount']>0 and display['beginCount']>0 and display['endCount']>0,'Actual native frame presentation was not observed')
    require(final['native_auth_ui_tested'] is False,'Unexpected native authentication UI claim')
    points=[];pre_world=[];world_started=False
    for event in events:
        event_state=event.get('state',{})
        world_started=world_started or event['event']=='native_world_start_builder' or (
            event_state.get('authenticated') is True and event_state.get('worldStartSent') is True)
        d=event.get('display',{})
        if 'uiHd' not in d:continue
        drawing_required=world_started or event['event']=='screen_qa_final'
        point=validate_hd(d['uiHd'],manifest,require_draws=drawing_required)
        point.update(utc=event['utc'],event=event['event'],present_count=d['presentCount'])
        if drawing_required:
            points.append(point)
        else:
            pre_world.append({'utc':event['utc'],'event':event['event'],
                'font_density_atlases_loaded':point['font_density_atlases_loaded'],
                'unique_icon_density_textures':point['unique_icon_density_textures'],
                'counters':point['counters'],'draws_required':False})
    require(points,'No complete actual HD resource/draw observations')
    last=validate_hd(display['uiHd'],manifest)
    resets=[e for e in events if e['event']=='screen_d3d_reset']
    for reset in resets:
        require(reset['hresult']==0 and reset['activeScene'] is False and reset['resetOnRenderThread'] is True and reset['thread']==reset['renderThread'],'D3D Reset did not return S_OK safely on the render thread')
        before=[p for p in points if stamp(p['utc'])<stamp(reset['utc'])]
        after=[p for p in points if stamp(p['utc'])>stamp(reset['utc'])]
        require(before and after,'Reset lacks HD status observations on both sides')
        b,a=before[-1],after[-1]
        require(all(a['counters'][k]>b['counters'][k] for k in b['counters']),'Font/icon drawing or pixel snapping did not continue after Reset')
        require(a['present_count']>b['present_count'],'Frames did not continue after Reset')
        for key in ('font_objects','font_textures','icon_textures'):
            require(a[key]==b[key],'Native cache/font identity changed across Reset: '+key)
    snapshots=[e for e in events if e['event']=='screen_native_snapshot']+display.get('snapshots',[])
    effective={s['uiScale']['effectivePercent'] for s in snapshots if 'uiScale' in s}
    return {'input':identity(path),'native_pid':ready[0]['pid'],'bridge_pid':ready[0]['bridge_pid'],
        'native_authenticated':True,'world_start_sent':True,'rendered_frames':display['presentCount'],'failures':0,
        'pre_world_resource_observations':pre_world,
        'first_hd_utc':points[0]['utc'],'final_hd_utc':points[-1]['utc'],'final_counters':last['counters'],
        'native_font_and_texture_identity_retained_across_reset':bool(resets),
        'actual_font_draw_densities':sorted({s['density'] for s in last['font_samples']}),
        'actual_icon_draw_densities':sorted({s['density'] for s in last['icon_samples']}),
        'effective_gui_scales_observed':sorted(effective),'resets':[{'utc':r['utc'],'hresult':r['hresult'],'thread':r['thread'],'outside_scene':True} for r in resets],
        'final_hd':last}

def verify(args):
    require(re.fullmatch('[0-9a-f]{64}',args.candidate_sha),'Exact candidate SHA256 is required')
    require(digest(args.candidate)==args.candidate_sha,'Saved candidate bytes differ')
    from tools import build_ui_hd_client as builder
    candidate,intermediate=builder.reconstruct()
    require(hashlib.sha256(candidate).hexdigest()==args.candidate_sha and candidate==Path(args.candidate).read_bytes(),'Candidate does not reconstruct from the frozen font/icon modules')
    predecessor=builder.preserve(builder.BASE.read_bytes(),candidate)
    fp=read_json(args.font_proof);ip=read_json(args.icon_proof)
    require(fp['result']=='PASS' and fp['checks']>=969 and fp['candidate_sha256']==hashlib.sha256(intermediate).hexdigest(),'Corrected native managed-font proof is not bound to this component')
    require(fp['source_file_sha256']==digest(fonts.__file__) and fp['ti_sha256']==fonts.TI_SHA,'Font proof source/TI changed')
    require(fp['native_basename_cache_executed'] is True and fp['native_unique_font_density_cache_keys']==36,'Actual native Unicode filename/cache proof is absent')
    require(ip['result']=='PASS' and ip['case_count']>=560 and ip['candidate_sha256']==args.candidate_sha,'Corrected native icon cache proof is not bound to this candidate')
    require(ip['source_sha256']==fp['candidate_sha256'] and ip['native_unique_density_texture_objects']==60 and ip['native_basename_cache_executed'] is True,'Native icon basename/density proof is incomplete')
    manifest=fonts.assets_manifest()
    runs=[validate_run(args.events_a,manifest),validate_run(args.events_b,manifest)]
    require(len({r[k] for r in runs for k in ('native_pid','bridge_pid')})==4,'Expected two independent owned native/bridge process pairs')
    fd={d for r in runs for d in r['actual_font_draw_densities']};idens={d for r in runs for d in r['actual_icon_draw_densities']}
    require({100,125,150}<=fd and {100,125,150}<=idens,'Actual GUI font/icon density draws at100/125/150 are incomplete')
    require(sum(len(r['resets']) for r in runs)==1,'Expected exactly one actual successful Reset across the owned A/B pair')
    continuity=None
    require(bool(args.before)==bool(args.after),'Provide both saved continuity snapshots')
    if args.before:
        from tools.verify_owned_ui_connection_continuity import compare
        before=read_json(args.before);after=read_json(args.after)
        require(before['native_candidate_sha256']==args.candidate_sha and after['native_candidate_sha256']==args.candidate_sha,'Actual loaded Silver identity differs from the candidate')
        facts=compare(before,after)
        expected={('game-'+label,r['native_pid'],r['bridge_pid']) for label,r in zip(('a','b'),runs)}
        require({(p['label'],p['native_pid'],p['bridge_pid']) for p in before['owned_pairs']}==expected,'Saved native/bridge identity does not bind to these event logs')
        reset=next(r for run in runs for r in run['resets'])
        require(stamp(before['captured_utc'])<stamp(reset['utc'])<stamp(after['captured_utc']),'TCP continuity does not bracket the actual Reset')
        continuity={'before':identity(args.before),'after':identity(args.after),**facts}
    screenshots=[identity(p) for p in args.screenshot]
    return {'result':'PASS','creator':'tools/verify_ui_hd_graphical_evidence.py','candidate_sha256':args.candidate_sha,
        'candidate':identity(args.candidate),'automated_native_proofs':{'fonts':identity(args.font_proof),'font_checks':fp['checks'],'icons':identity(args.icon_proof),'icon_checks':ip['case_count'],'densities':[100,125,150,200]},
        'predecessor_runtime_byte_identical':predecessor,'actual_owned_clients':runs,'actual_gui_font_densities':sorted(fd),
        'actual_gui_icon_densities':sorted(idens),'actual_gui_200_tested':200 in fd and 200 in idens,
        'all_nine_font_roles_loaded_at_four_densities':True,'all_fifteen_icon_resources_loaded_at_four_unique_densities':True,
        'texture_dimension_evidence':'Native allocation fields +0x14/+0x18 with live +0x0c D3D handles; this tool makes no independent COM GetLevelDesc call.',
        'successful_actual_resets':1,'tcp_continuity':continuity,'actual_loaded_candidate_file_identity_bound':bool(continuity),
        'screenshots':screenshots,'screenshots_visually_examined_by_this_tool':False,'native_auth_ui_tested':False,
        'battle_retested_for_this_asset_change':False,'obs_source_transform_tested':False,'exclusive_fullscreen_tested':False,
        'validator_processes_opened':False,'validator_ui_operations':False,'validator_remote_requests':False,
        'published':False,'candidate_publish_allowed':False,'source_file_sha256':digest(__file__)}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--candidate-sha',required=True);p.add_argument('--candidate',type=Path,default=DEFAULT_CANDIDATE)
    p.add_argument('--events-a',type=Path,required=True);p.add_argument('--events-b',type=Path,required=True)
    p.add_argument('--font-proof',type=Path,default=FONT_PROOF);p.add_argument('--icon-proof',type=Path,required=True)
    p.add_argument('--before',type=Path);p.add_argument('--after',type=Path);p.add_argument('--screenshot',type=Path,action='append',default=[])
    p.add_argument('--out',type=Path,required=True);args=p.parse_args()
    try:report=verify(args)
    except (ValueError,KeyError,TypeError,StopIteration) as error:
        report={'result':'FAIL','error':str(error),'candidate_sha256':args.candidate_sha,'processes_opened':False,'published':False}
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('result','candidate_sha256')}))
    if report['result']!='PASS':print(report['error']);raise SystemExit(1)
if __name__=='__main__':main()
