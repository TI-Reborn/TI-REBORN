"""Distinct functional surroundings, using verified city sprites at 1:1."""
from __future__ import annotations
import hashlib
import math
import random

SIDES=('x_negative','y_negative','x_at_or_above_width','y_at_or_above_width')

# Side, position along side, distance from edge, sprite, function.
# Buildings are accents. Infrastructure is the only repeated continuous layer.
FEATURES={
 'R1':[(0,.12,4,'oil_tank_01','tank'),(1,.64,8,'oil_tank_01b','tank'),
       (1,.37,4,'cargo_army_01b','vehicle'),(3,.76,5,'oil_tank_01','tank')],
 'R2':[(0,.10,4,'hangar','building'),(1,.65,7,'shed','building'),
       (2,.33,5,'shed','building'),(3,.72,8,'hangar','building')],
 'R3':[],
 'D1':[],
 'D2':[(0,.12,3,'ground_forest_ravine_v1','landform'),
       (3,.60,6,'ground_forest_ravine_v1p','landform')],
 'D3':[(0,.16,4,'forest_house','building'),(1,.64,8,'forest_house','building'),
       (2,.25,5,'forest_house','building'),(3,.76,3,'forest_house','building')],
 'N1':[(0,.14,4,'ny_clinic','building'),(1,.67,7,'ny_clinic','building'),
       (2,.37,4,'ny_car_v01','vehicle'),(3,.74,5,'ny_car_v01b','vehicle')],
 'N2':[(0,.12,3,'ny_car_v01','vehicle'),(0,.31,3,'ny_car_v01b','vehicle'),
       (1,.63,4,'ny_car_v02b','vehicle'),(1,.79,7,'ny_car_v01','vehicle'),
       (2,.22,3,'ny_car_truck_v01','vehicle'),(3,.60,3,'ny_car_v01b','vehicle'),
       (3,.76,7,'ny_car_v02b','vehicle')],
 'N3':[(0,.10,4,'ny_livhouse_v01','building'),(1,.68,7,'ny_livhouse_v01','building'),
       (2,.46,6,'ny_clinic','building'),(3,.76,4,'ny_car_v01b','vehicle'),
       (3,.24,6,'water_tower','utility')],
 'M1':[(0,.12,4,'hangar','building'),(1,.65,8,'hangar','building'),
       (2,.31,5,'shed','building'),(3,.74,7,'tent','building'),
       (1,.24,4,'water_tower','utility')],
 'M2':[(0,.11,5,'shed','building'),(1,.64,8,'shed','building'),
       (3,.73,4,'shed','building'),(2,.24,5,'cargo_army_01b','vehicle')],
 'M3':[(0,.12,4,'tent','building'),(0,.36,8,'tent','building'),
       (1,.68,5,'tent','building'),(2,.29,7,'tent','building'),(3,.74,4,'tent','building')],
}

NY_GROUPS=(
 ('service',['ny_hydrant','ny_hatch','ny_lamppost_dl','ny_mailbox_dl','ny_canister_v02']),
 ('recycling',['ny_trash_container_v01','ny_trashbag_pile_v01','ny_paperbox_v02b','ny_newspaper_v01','ny_canister_v03','ny_trash_v01']),
 ('vehicle_repair',['ny_whell','ny_carjunk_v02','ny_carjunk_v04','ny_canister_v01','ny_trash_v02']),
 ('courtyard',['ny_mailbox_ur','ny_lamppost_dr','ny_trash_container_v04','ny_bottlepack_v03','village_bench_01']),
 ('discarded_supplies',['ny_paperbox_v01b','ny_trashbag_v04','ny_carjunk_v05','ny_newspaper_v02','ny_newspaper_v03','ny_boxcart_v02']),
)
INDUSTRIAL_GROUPS=(
 ('fuel',['barrel_01','barrel_02','barrel_03','metal_pipe_01b','cord_roll_01']),
 ('loading',['wood_box_pile_02','wood_box_column_01','paper_box_02b','item_steel_box_01','wood_box_03','wood_box_pile_05']),
 ('repair',['tire_pile_01','tire_05','cord_roll_02','item_steel_box_01b','metal_pipe_02','shelves_01']),
 ('storage',['wood_box_column_03','wood_box_pile_07','paper_box_03b','wood_box_02b','barrel_03','shelves_01b']),
 ('maintenance',['fence_sign_01a','metal_pipe_01','paper_box_01b','tire_02','wood_box_01','barrel_02']),
)
FOREST_GROUPS=(
 ('fallen_timber',['log_single_01','forest_stub_v1','forest_bush_v2','forest_indoor_logs_v1']),
 ('undergrowth',['forest_bush_v1','forest_bush_v3','forest_bush_v2','log_single_01b']),
 ('old_clearing',['forest_stub_v1','log_single_01b','forest_bush_v3','forest_bush_v1']),
)
VILLAGE_GROUPS=(
 ('household',['village_bench_01b','forest_indoor_pot_v1','forest_bush_v2','forest_indoor_waterbarrel_v1']),
 ('firewood',['forest_indoor_axe_v1','forest_indoor_logs_v1','log_single_01','forest_indoor_crowbar','forest_bush_v3']),
 ('workyard',['forest_indoor_heater','forest_indoor_shelves_p','forest_indoor_waterbarrel_v1','log_single_01b','forest_bush_v1']),
)


def build_layout(master_id,width,depth,lookup,outside_origin):
    seed=int.from_bytes(hashlib.sha256(f'city-environment-v3:{master_id}:{width}'.encode()).digest()[:8],'little')
    rng=random.Random(seed)
    placements=[]
    occupied=[]
    def add(side,along,margin,identity,role,group,layer=1,avoid_buildings=False):
        item=lookup(identity)
        if item is None:
            return False
        along=round(along*4)/4
        margin=round(margin*4)/4
        x,y=outside_origin(side,item,along,margin)
        if avoid_buildings:
            for offset in (0,2,-2,4,-4,7,-7,10,-10):
                xx,yy=outside_origin(side,item,along+offset,margin)
                fw,fh=item[0]['world_footprint']
                rect=(xx,yy,xx+max(1,fw),yy+max(1,fh))
                if not any(rect[0]<r[2] and rect[2]>r[0] and rect[1]<r[3] and rect[3]>r[1] for r in occupied):
                    x,y=xx,yy
                    break
            else:
                return False
        placements.append((x,y,side,layer,item,role,group))
        if role=='building':
            _,xmax,_,ymax=item[3]
            occupied.append((x-1,y-1,x+max(item[0]['world_footprint'][0],math.ceil(xmax))+1,
                             y+max(item[0]['world_footprint'][1],math.ceil(ymax))+1))
        return True

    for index,(side,t,margin,identity,role) in enumerate(FEATURES[master_id]):
        add(SIDES[side],t*width,margin,identity,role,'landmark_'+str(index))

    if master_id in ('D1','D2','D3'):
        groves=((0,.15,3,3),(0,.75,7,5),(1,.55,4,4),(2,.30,6,3),(3,.74,5,5))
        for group,(side,t,normal,count) in enumerate(groves):
            if master_id!='D1': count=min(2,count)
            for index in range(count):
                identity='forest_tree_v'+str(1+(index+group)%5)
                add(SIDES[side],t*width+rng.uniform(-4,4),normal+rng.uniform(0,5),
                    identity,'canopy','grove_'+str(group),avoid_buildings=True)

    # Roads form the underlay. Walls participate in normal painter depth so
    # objects behind the boundary do not appear on top of its front face.
    barrier_ids=None
    if master_id.startswith('N') and master_id!='N2':
        barrier_ids=('ny_wall_dl_v01','ny_wall_ul_v01','ny_wall_ur_v01','ny_wall_dr_v01')
    elif master_id=='R1': barrier_ids=('steel_fence_01b','steel_fence_01','steel_fence_01b','steel_fence_01')
    elif master_id=='M1': barrier_ids=('concrete_wall_01b','concrete_wall_01','concrete_wall_01b','concrete_wall_01')
    barrier_normals=[]
    if barrier_ids:
        for side_index,side in enumerate(SIDES):
            origin=outside_origin(side,lookup(barrier_ids[side_index]),0,1)
            barrier_normals.append(origin[0 if side.startswith('x_') else 1])
    for side_index,side in enumerate(SIDES):
        if master_id=='N2' or master_id=='N3' and side_index==2:
            road_positions=range(-4,width+4,4) if master_id=='N2' else range(int(width*.48),int(width*.48)+12,4)
            for normal in ((0,4) if master_id=='N2' else (0,)):
                for index,along in enumerate(road_positions):
                    add(side,along,1+normal,'ny_road_v01' if side_index in (0,3) else 'ny_road_v02',
                        'road','road_'+str(side_index),layer=0)
        identity=barrier_ids[side_index] if barrier_ids else None
        if identity:
            item=lookup(identity)
            stride=max(1,math.ceil(item[0]['world_footprint'][1 if side.startswith('x_') else 0]))
            other_axis=(1,3) if side.startswith('x_') else (0,2)
            along=barrier_normals[other_axis[0]]
            end=barrier_normals[other_axis[1]]
            while along<end:
                add(side,along,1,identity,'barrier','boundary_'+str(side_index),layer=1)
                along+=stride

    if master_id.startswith('N'): groups=NY_GROUPS
    elif master_id=='D3': groups=VILLAGE_GROUPS
    elif master_id.startswith('D'): groups=FOREST_GROUPS
    else: groups=INDUSTRIAL_GROUPS
    for side_index,side in enumerate(SIDES):
        centers=(.12,.48,.83)
        for group_index,center in enumerate(centers):
            name,identities=groups[(side_index*2+group_index+int(master_id[1])-1)%len(groups)]
            along=center*width+rng.uniform(-1.5,1.5)
            normal=(8 if master_id=='R3' else 2)+rng.uniform(0,5)
            for index,identity in enumerate(identities):
                add(side,along+rng.uniform(-3.25,3.25),normal+rng.uniform(0,3.25),
                    identity,'detail',f'{side_index}_{group_index}_{name}',avoid_buildings=True)
            # A second, looser band of local clutter makes each node irregular.
            for index in range(2+((side_index+group_index)%3)):
                identity=identities[rng.randrange(len(identities))]
                add(side,along+rng.uniform(-5,5),normal+4+rng.uniform(0,4),
                    identity,'detail',f'{side_index}_{group_index}_{name}_spill',avoid_buildings=True)
    if master_id.startswith('N'):
        for side,t,identity in ((1,.22,'ny_tree_lw_v02'),(3,.43,'ny_tree_rw_v03')):
            add(SIDES[side],width*t,7,identity,'canopy','street_green',avoid_buildings=True)
    if master_id.startswith('D'):
        for side_index,side in enumerate(SIDES):
            for index,t in enumerate((.30,.55,.88)):
                for offset,identity in ((-1,'forest_bush_v2'),(1,'forest_stub_v1'),(2.5,'log_single_01b')):
                    add(side,width*t+offset+rng.uniform(-.75,.75),1+rng.uniform(0,2),identity,
                        'detail',f'edge_{side_index}_{index}',avoid_buildings=True)
    return placements,dict(layout_version=3,seed=seed,large_building_limit=6,
        functional_nodes=True,regular_building_rows=False,clusters=len({p[6] for p in placements if p[5]=='detail'}))
