"""Independent reconstruction of plan lines from workbook vertices.

No imports from physical_axes, segmentation or the numbering implementation.
"""

from collections import defaultdict
from cmath import phase, rect
from dataclasses import replace
from math import cos, floor, hypot, radians
from shapely.geometry import LineString, Point

from services.audit_numbering import audited_axis_assignment, format_designation

EPS=1e-9


def reference_direction(groups,copies,config):
    if config.line_azimuth is not None:
        return rect(1,radians(90-config.line_azimuth))
    buckets=defaultdict(complex)
    weights=defaultdict(float)
    for key,g in groups.items():
        if key in copies or g.polyline is None or g.closed:
            continue
        for a,b in zip(g.coords,g.coords[1:]):
            delta=complex(b[0]-a[0],b[1]-a[1])
            size=abs(delta)
            if size>EPS:
                slot=int(floor((phase(delta)*180/3.141592653589793%180+.5)%180))
                weights[slot]+=size
                buckets[slot]+=delta*delta/size
    if not weights:
        return 1+0j
    best=min(weights,key=lambda k:(-weights[k],k))
    return rect(1,phase(buckets[best])/2)


def _is_straight(a,b,direction,config):
    delta=complex(b[0]-a[0],b[1]-a[1])
    return abs(delta)>EPS and abs((delta/direction).real)/abs(delta)>=cos(radians(config.line_angle))-1e-12


def _collinear(a,b,tolerance,angle):
    for ai,aj in ((0,1),(-1,-2)):
        for bi,bj in ((0,1),(-1,-2)):
            p,q=a[ai],b[bi]
            gap=abs(complex(p[0]-q[0],p[1]-q[1]))
            if gap>tolerance+EPS or (p[2] is not None and q[2] is not None and abs(p[2]-q[2])>tolerance+EPS):
                continue
            v=complex(a[aj][0]-p[0],a[aj][1]-p[1])
            w=complex(b[bj][0]-q[0],b[bj][1]-q[1])
            if abs(v)*abs(w)>EPS*EPS and (v.conjugate()*w).real/(abs(v)*abs(w)) <= -cos(radians(angle))+1e-12:
                return True
    one,two=a[0],a[-1]
    three,four=b[0],b[-1]
    origin=complex(one[0],one[1])
    delta=complex(two[0]-one[0],two[1]-one[1])
    other=complex(four[0]-three[0],four[1]-three[1])
    if abs(delta)<=EPS or abs(other)<=EPS:
        return False
    unit=delta/abs(delta)
    unit2=other/abs(other)
    if max(abs(((complex(p[0],p[1])-origin)/unit).imag) for p in b)>tolerance+EPS:
        return False
    origin2=complex(three[0],three[1])
    if max(abs(((complex(p[0],p[1])-origin2)/unit2).imag) for p in a)>tolerance+EPS:
        return False
    left=[(complex(p[0],p[1])/unit).real for p in a]
    right=[(complex(p[0],p[1])/unit).real for p in b]
    lo,hi=max(min(left),min(right)),min(max(left),max(right))
    if lo>hi+tolerance+EPS:
        return False
    if all(p[2] is not None for p in (one,two,three,four)):
        at=(lo+hi)/2
        def elevation(p,q):
            start=(complex(p[0],p[1])/unit).real
            end=(complex(q[0],q[1])/unit).real
            return p[2]+(q[2]-p[2])*(at-start)/(end-start) if abs(end-start)>EPS else p[2]
        if abs(elevation(one,two)-elevation(three,four))>tolerance+EPS:
            return False
    return True


def physical_assignment(groups,copies,config,*,paths=None,parents=None):
    contexts=defaultdict(dict)
    for key,g in groups.items():
        contexts[g.level,g.body][key]=g
    directions={key:reference_direction(items,copies,config) for key,items in contexts.items()}
    if paths is None:
        paths,parents={},{}
        for key,g in groups.items():
            direction=directions[g.level,g.body]
            if key in copies or g.polyline is None or g.closed:
                continue
            current=[]
            previous=None
            run=0
            for a,b in zip(g.coords,g.coords[1:]):
                state=_is_straight(a,b,direction,config)
                if previous!=state:
                    if current:
                        run+=1
                        paths[f"{key}:{run}"]=(tuple(current),)
                        parents[f"{key}:{run}"]=key
                    current=[a,b]
                else:
                    current.append(b)
                previous=state
            if current:
                run+=1
                paths[f"{key}:{run}"]=(tuple(current),)
                parents[f"{key}:{run}"]=key
    roles={}
    mixed=set()
    candidates={}
    dims=3 if config.length_mode=="XYZ" else 2
    for key,spans in paths.items():
        g=groups[parents[key]]
        direction=directions[g.level,g.body]
        if g.polyline is None or g.closed:
            roles[key]="unknown"
            continue
        flags=[_is_straight(a,b,direction,config) for path in spans for a,b in zip(path,path[1:])]
        if not flags:
            roles[key]="unknown"
        elif all(flags):
            roles[key]="line"
        elif any(flags):
            mixed.add(key)
            roles[key]="transition"
        else:
            roles[key]="transition"
        if (roles[key]=="line" and len(spans)==1 and not g.source_conflict and not g.pair_conflict
                and (len(spans[0])<3 or spans[0][0][:2]!=spans[0][-1][:2])):
            path=spans[0]
            length=sum(sum((b[i]-a[i])**2 for i in range(dims))**.5 for a,b in zip(path,path[1:]))
            if length:
                candidates[key]=path
    scopes=defaultdict(list)
    for key in candidates:
        g=groups[parents[key]]
        scopes[g.level,g.body].append(key)
    component={k:k for k in candidates}
    def leader(key):
        while component[key]!=key:
            component[key]=component[component[key]]
            key=component[key]
        return key
    for keys in scopes.values():
        for index,key in enumerate(keys):
            for other in keys[:index]:
                if _collinear(candidates[key],candidates[other],config.line_tolerance,config.line_angle):
                    x,y=leader(key),leader(other)
                    component[max(x,y)]=min(x,y)
    members=defaultdict(list)
    for key in candidates:
        members["L"+leader(key)].append(key)
    reference={}
    for root,keys in members.items():
        points=[p for key in keys for p in candidates[key]]
        levels=[p[2] for p in points if p[2] is not None]
        center=tuple((min(p[i] for p in points)+max(p[i] for p in points))/2 for i in (0,1))
        center+=( (min(levels)+max(levels))/2 if levels else None, )
        original=min((groups[parents[k]] for k in keys),key=lambda g:g.refs[0])
        category=config.priority if any(groups[parents[k]].source_category==config.priority for k in keys) else None
        reference[root]=replace(original,coords=(center,),polyline=1.,source_category=category,
                                 source_conflict=False,pair_conflict=False)
    ranks,_,_=audited_axis_assignment(reference,set(),replace(config,numbering_unit="source"))
    numbers={key:ranks[root] for root,keys in members.items() if root in ranks for key in keys}
    roots={key:root for root,keys in members.items() if root in ranks for key in keys}
    axis_values={key:tuple(sorted({numbers[k] for k,p in parents.items() if p==key and k in numbers})) for key in groups}
    axis_roots={key:{roots[k] for k,p in parents.items() if p==key and k in roots} for key in groups}
    transitions={}
    for key,role in roles.items():
        if role!="transition":
            continue
        g=groups[parents[key]]
        nearby=set()
        for path in paths[key]:
            for end in (path[0],path[-1]):
                point=Point(end[:2])
                for other in numbers:
                    h=groups[parents[other]]
                    if (h.level,h.body)==(g.level,g.body) and LineString([p[:2] for p in candidates[other]]).distance(point)<=config.line_tolerance+EPS:
                        nearby.add(numbers[other])
        transitions[key]=tuple(sorted(nearby))
    return numbers,roots,axis_values,axis_roots,roles,transitions,mixed


def physical_designations(groups,categories,numbers,roots,parents,axis_values,axis_roots,axis_categories,config):
    values={}
    markings=defaultdict(set)
    for key,number in numbers.items():
        g=groups[parents[key]]
        mark,name=format_designation(g,categories[key],number,config)
        values[key]=(number,mark,name)
        if mark:
            markings[mark].add(roots[key])
    for key,values_for_axis in axis_values.items():
        if len(values_for_axis)==1 and len(axis_roots[key])==1:
            mark,_=format_designation(groups[key],axis_categories[key],values_for_axis[0],config)
            if mark:
                markings[mark].update(axis_roots[key])
    return {key:(num,"" if len(markings[mark])>1 else mark,"" if len(markings[mark])>1 else name)
            for key,(num,mark,name) in values.items()}

