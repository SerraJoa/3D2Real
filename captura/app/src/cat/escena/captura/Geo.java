package cat.escena.captura;

/** Geometria pura (sense Android) per posar el que s'apunta en un pla a partir de l'IMU, l'alçada de la càmera i el terra. */
public final class Geo {
    private Geo() { }

    /**
     * Raig en coordenades món (x est, y nord, z amunt) del píxel (u,v) de la vista vertical.
     * R: matriu 3x3 dispositiu->món (SensorManager.getRotationMatrixFromVector); f en px de la vista; (cx,cy) centre.
     * Dispositiu: x dreta, y amunt, z cap a l'usuari; la càmera mira cap a -z. Píxel: u dreta, v avall.
     */
    public static float[] raig(float[] R, float f, float cx, float cy, float u, float v) {
        float dx = (u - cx) / f, dy = -(v - cy) / f, dz = -1f;
        float[] r = {
            R[0] * dx + R[1] * dy + R[2] * dz,
            R[3] * dx + R[4] * dy + R[5] * dz,
            R[6] * dx + R[7] * dy + R[8] * dz};
        float n = (float) Math.sqrt(r[0] * r[0] + r[1] * r[1] + r[2] * r[2]);
        r[0] /= n; r[1] /= n; r[2] /= n;
        return r;
    }

    /** Punt del terra (x,y relatius a la càmera, en m) on cau el raig, o null si no mira prou cap avall. */
    public static float[] terra(float[] raig, float alcadaCam) {
        if (raig[2] > -0.03f) return null;
        float t = -alcadaCam / raig[2];
        return new float[]{raig[0] * t, raig[1] * t};
    }

    /** Alçada sobre el terra d'un punt que és verticalment sobre la base (x,y), vist amb aquest raig. */
    public static float alcadaSobreBase(float[] raig, float alcadaCam, float distHoritzontalBase) {
        float hz = (float) Math.hypot(raig[0], raig[1]);
        if (hz < 1e-4f) return Float.NaN;
        return alcadaCam + distHoritzontalBase * (raig[2] / hz);
    }

    /** Línia de l'horitzó a la vista: retorna v per a un u donat (NaN si és vertical). */
    public static float horitzoV(float[] R, float f, float cx, float cy, float u) {
        float xn = (u - cx) / f, a = R[6], b = R[7], c = R[8];
        if (Math.abs(b) < 1e-3f) return Float.NaN;
        float yn = (a * xn - c) / b;               // z món = a·xn − b·yn − c = 0
        return cy + f * yn;
    }
}
