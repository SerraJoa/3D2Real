import math

import numpy as np
import pytest

import sfm_poses as sp


def _camera(az, el, dist, roll, mir_y):
    """Càmera (centre, rotació món→càmera OpenCV) de l'escena del visor, amb la definició del visor."""
    a, e = math.radians(az), math.radians(el)
    C = np.array([dist * math.cos(e) * math.sin(a), dist * math.sin(e), -dist * math.cos(e) * math.cos(a)])
    f = sp._unit(np.array([0.0, mir_y, 0.0]) - C)
    u0 = sp._unit(np.array([0.0, 1.0, 0.0]) - f[1] * f)
    r = math.radians(roll)
    up = u0 * math.cos(r) + np.cross(f, u0) * math.sin(r)           # Rodrigues: gira u0 al voltant de f, sentit dret
    right = np.cross(f, up)
    return C, np.vstack([right, -up, f])


def _sessio(n=12, escala_mon=0.37, seed=3):
    rng = np.random.default_rng(seed)
    Q = np.linalg.qr(rng.normal(size=(3, 3)))[0]
    if np.linalg.det(Q) < 0:
        Q[:, 0] *= -1
    shift = np.array([2.0, -1.0, 5.0])
    veritat, C, R = [], [], []
    for k in range(n):
        az = 360.0 * k / n + 7
        el = 8 + 14 * (k % 3)
        v = dict(az=az, el=el, dist=55 + 6 * (k % 4), roll=[-4, 0, 3, 1][k % 4], mir_y=4 + 2 * (k % 3))
        c, r = _camera(v["az"], v["el"], v["dist"], v["roll"], v["mir_y"])
        C.append(escala_mon * (Q @ c) + shift); R.append(r @ Q.T)
        veritat.append(v)
    anell = [(40 * math.sin(t), 0, -40 * math.cos(t)) for t in np.linspace(0, 6.28, 200)]
    cos = [(rng.uniform(-8, 8), rng.uniform(2, 9), rng.uniform(-8, 8)) for _ in range(100)]
    pts = escala_mon * (Q @ np.array(anell + cos).T).T + shift
    return veritat, np.array(C), np.array(R), pts


def test_recupera_azimut_elevacio_distancia_roll_i_mirada():
    v, C, R, pts = _sessio()
    poses, tr = sp.poses_visor(C, R, [(1080, 1920)] * len(C), [1565.0] * len(C), radi=60.0, punts=pts)
    esc = 60.0 / np.median([math.hypot(x["dist"] * math.cos(math.radians(x["el"]))) for x in v])
    for i, (p, t) in enumerate(zip(poses, v)):
        d_az = (p["az"] - 180.0) - (t["az"] - v[0]["az"])
        assert (d_az + 180) % 360 - 180 == pytest.approx(0, abs=0.5)
        assert p["el"] == pytest.approx(t["el"], abs=1.0)
        assert p["dist"] == pytest.approx(t["dist"] * esc, rel=0.03)
        assert p["roll"] == pytest.approx(t["roll"], abs=1.0)
        assert p["mirY"] == pytest.approx(t["mir_y"] * esc, abs=1.0)
        assert p["desviacio_graus"] < 1.0


def test_gir_suma_a_tots_els_azimuts():
    v, C, R, pts = _sessio()
    a, _ = sp.poses_visor(C, R, [(1080, 1920)] * len(C), [1565.0] * len(C), punts=pts)
    b, _ = sp.poses_visor(C, R, [(1080, 1920)] * len(C), [1565.0] * len(C), punts=pts, gir=30)
    for x, y in zip(a, b):
        assert ((y["az"] - x["az"] - 30 + 180) % 360 - 180) == pytest.approx(0, abs=1e-6)


def test_fov_del_costat_llarg_i_horitzontal():
    v, C, R, pts = _sessio(6)
    p, _ = sp.poses_visor(C, R, [(1080, 1920)] * 6, [1565.0] * 6, punts=pts)
    assert p[0]["fov_costat_llarg"] == pytest.approx(2 * math.degrees(math.atan(960 / 1565)), abs=1e-6)
    assert p[0]["fov_horitzontal"] < p[0]["fov_costat_llarg"]            # apaïsada → l'amplada és el costat curt


def test_aplica_porta_les_camares_a_la_seva_posicio():
    v, C, R, pts = _sessio()
    poses, tr = sp.poses_visor(C, R, [(1080, 1920)] * len(C), [1565.0] * len(C), punts=pts)
    S = sp.aplica(tr, C)
    assert np.allclose(np.linalg.norm(S, axis=1), [p["dist"] for p in poses], atol=1e-6)
    assert np.allclose(S[:, 1], [p["dist"] * math.sin(math.radians(p["el"])) for p in poses], atol=1e-6)


def test_tria_per_azimut_agafa_una_per_sector_amb_mes_pes():
    poses = [dict(az=a) for a in (10, 20, 100, 200, 210, 300)]
    assert sp.tria_per_azimut(poses, [1, 5, 2, 3, 9, 4], 4) == [1, 2, 4, 5]


def test_menys_de_3_camares_es_error():
    with pytest.raises(ValueError, match="almenys 3"):
        sp.poses_visor(np.zeros((2, 3)), np.tile(np.eye(3), (2, 1, 1)), [(10, 10)] * 2, [10.0] * 2)
