
import math, tempfile
from pathlib import Path
import numpy as np
import streamlit as st
import trimesh

st.set_page_config(page_title="3D → PaperCraft", layout="wide")
st.title("✂️ 3D → PaperCraft — MVP v2")
st.caption("Malla 3D → simplificació → desplegament → costures → pestanyes → SVG")

def load_mesh(data, name):
    suffix=Path(name).suffix.lower()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(data); path=f.name
    obj=trimesh.load(path, force="scene")
    if isinstance(obj,trimesh.Scene):
        ms=[g for g in obj.geometry.values() if isinstance(g,trimesh.Trimesh)]
        if not ms: raise ValueError("No s'ha trobat cap malla.")
        obj=trimesh.util.concatenate(ms)
    obj.remove_unreferenced_vertices()
    return obj

def simplify(mesh,target):
    if len(mesh.faces)<=target: return mesh.copy()
    for args in [dict(face_count=target),dict(target_faces=target)]:
        try: return mesh.simplify_quadric_decimation(**args)
        except Exception: pass
    raise RuntimeError("Cal una versió de trimesh amb suport per a simplificació quadric.")

def adjacency(mesh):
    faces=mesh.faces
    em={}
    for fi,f in enumerate(faces):
        for i in range(3):
            e=tuple(sorted((int(f[i]),int(f[(i+1)%3]))))
            em.setdefault(e,[]).append(fi)
    pairs={}
    neigh=[[] for _ in faces]
    for e,fs in em.items():
        if len(fs)==2:
            a,b=fs
            neigh[a].append(b); neigh[b].append(a)
            pairs[(a,b)]=e; pairs[(b,a)]=e
    return neigh,pairs,em

def orient_triangle(A,B,L0,L1,side):
    d=np.linalg.norm(B-A)
    if d<1e-9:return None
    x=(L0*L0-L1*L1+d*d)/(2*d)
    h=math.sqrt(max(L0*L0-x*x,0))
    u=(B-A)/d
    perp=np.array([-u[1],u[0]])
    return A+u*x+perp*h*side

def unfold(mesh, root=0, preferred_cuts=set()):
    V,F=mesh.vertices,mesh.faces
    neigh,pairs,em=adjacency(mesh)
    placed={root:None}
    # Place root at real scale.
    f=F[root]; a,b,c=V[f]
    A=np.array([0.,0.]); B=np.array([np.linalg.norm(b-a),0.])
    C=orient_triangle(A,B,np.linalg.norm(c-a),np.linalg.norm(c-b),1)
    placed[root]=np.array([A,B,C])
    q=[root]
    while q:
        fi=q.pop(0)
        f=F[fi]
        for nb in neigh[fi]:
            if nb in placed or (fi,nb) in preferred_cuts: continue
            e=pairs[(fi,nb)]
            inds=list(f)
            try:i0,i1=inds.index(e[0]),inds.index(e[1])
            except:continue
            A,B=placed[fi][i0],placed[fi][i1]
            g=F[nb]
            k=next((z for z,x in enumerate(g) if int(x) not in e),None)
            if k is None:continue
            L0=np.linalg.norm(V[g[k]]-V[e[0]])
            L1=np.linalg.norm(V[g[k]]-V[e[1]])
            parent_k=next((z for z,x in enumerate(f) if int(x) not in e),None)
            P=placed[fi][parent_k]
            s=1 if np.cross(B-A,P-A)<0 else -1
            C=orient_triangle(A,B,L0,L1,s)
            coords=[]
            for x in g:
                if int(x)==e[0]:coords.append(A)
                elif int(x)==e[1]:coords.append(B)
                else:coords.append(C)
            placed[nb]=np.array(coords);q.append(nb)
    return placed, pairs, em

def polygon_overlap(a,b):
    # SAT for triangles: if projections overlap on all edge normals, they overlap.
    def axes(p):
        out=[]
        for i in range(3):
            d=p[(i+1)%3]-p[i]
            n=np.array([-d[1],d[0]])
            l=np.linalg.norm(n)
            if l>1e-9: out.append(n/l)
        return out
    for ax in axes(a)+axes(b):
        pa=a@ax; pb=b@ax
        if pa.max()<pb.min()-1e-7 or pb.max()<pa.min()-1e-7:return False
    return True

def optimize_cuts(mesh, placed, pairs):
    # Mark shared edges whose two faces overlap after unfolding.
    bad=set()
    items=list(placed.items())
    for i in range(len(items)):
        fi,pi=items[i]
        for j in range(i+1,len(items)):
            fj,pj=items[j]
            if fj==fi:continue
            if polygon_overlap(pi,pj):
                if (fi,fj) in pairs: bad.add((fi,fj))
                elif (fj,fi) in pairs: bad.add((fj,fi))
    return bad

def svg_export(mesh,placed,pairs,cut_edges,tab_mm,fold_width=0.35):
    allp=np.vstack(list(placed.values()))
    minx,miny=allp.min(axis=0); maxx,maxy=allp.max(axis=0)
    margin=12+tab_mm
    W=maxx-minx+2*margin; H=maxy-miny+2*margin
    def tr(p): return np.array([p[0]-minx+margin, H-(p[1]-miny+margin)])
    out=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.2f}mm" height="{H:.2f}mm" viewBox="0 0 {W:.2f} {H:.2f}">']
    out.append('<g stroke="black" stroke-width="0.25" fill="white">')
    for fi,p in placed.items():
        q=[tr(x) for x in p]
        out.append('<polygon points="'+" ".join(f"{x:.2f},{y:.2f}" for x,y in q)+'"/>')
    out.append('</g>')
    # Fold lines: shared edges that are NOT cuts.
    out.append('<g stroke="black" stroke-width="0.25" stroke-dasharray="2,1" fill="none">')
    for (a,b),e in pairs.items():
        if a>b or (a,b) in cut_edges:continue
        if a not in placed or b not in placed:continue
        f=mesh.faces[a]; ia=list(f).index(e[0]); ib=list(f).index(e[1])
        p1,p2=tr(placed[a][ia]),tr(placed[a][ib])
        out.append(f'<line x1="{p1[0]:.2f}" y1="{p1[1]:.2f}" x2="{p2[0]:.2f}" y2="{p2[1]:.2f}"/>')
    out.append('</g>')
    # Labels
    out.append('<g font-family="sans-serif" font-size="3" fill="black" stroke="none">')
    for fi,p in placed.items():
        c=tr(p.mean(axis=0))
        out.append(f'<text x="{c[0]:.2f}" y="{c[1]:.2f}">{fi+1}</text>')
    out.append('</g></svg>')
    return "\n".join(out)

uploaded=st.file_uploader("Carrega STL o OBJ",type=["stl","obj"])
if uploaded:
    try:
        mesh=load_mesh(uploaded.getvalue(),uploaded.name)
        st.success(f"{len(mesh.faces):,} cares · {len(mesh.vertices):,} vèrtexs")
        maxf=max(10,len(mesh.faces))
        target=st.slider("Simplificació — nombre de cares",10,maxf,max(20,min(maxf,300)))
        tab=st.slider("Amplada de pestanyes (mm)",2.0,12.0,5.0,0.5)
        auto=st.checkbox("Intentar separar solapaments automàticament",True)
        if st.button("🚀 Generar desplegable",type="primary"):
            simple=simplify(mesh,target)
            placed,pairs,em=unfold(simple)
            cuts=set()
            if auto:
                cuts=optimize_cuts(simple,placed,pairs)
            svg=svg_export(simple,placed,pairs,cuts,tab)
            st.session_state["svg"]=svg
            st.session_state["faces"]=len(simple.faces)
            st.session_state["cuts"]=len(cuts)
            st.success(f"Generat: {len(simple.faces)} cares · {len(cuts)} costures separades")
        if "svg" in st.session_state:
            st.download_button("⬇️ Descarrega SVG",st.session_state["svg"],"papercraft.svg","image/svg+xml")
            st.info("Línia contínua = tall. Línia discontínua = plegat. Els números identifiquen les cares.")
    except Exception as e:
        st.error(str(e))

st.markdown("---")
st.subheader("Roadmap")
st.write("MVP v2: costures i plecs bàsics. Següent: pestanyes geomètriques reals, connexions numerades, evitar solapaments de manera iterativa i PDF d'impressió.")
