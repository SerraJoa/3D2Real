package cat.escena.captura;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.view.MotionEvent;
import android.view.View;

import java.util.ArrayList;
import java.util.List;

/** Capa sobre la vista prèvia: horitzó de l'IMU, creu central i pla (vista de planta) de l'estació actual. */
public class Overlay extends View {
    /** Dades d'una estació: punts de cantonada (x,y m) i objectes (x,y,alçada m) respecte de la càmera. */
    public static class Estacio {
        public final List<float[]> cant = new ArrayList<>();
        public final List<float[]> obj = new ArrayList<>();
        public float[] ref;          // direcció de referència (yaw del dispositiu quan comença l'estació): x,y unitari
    }

    public interface Toc { void alToc(float u, float v); }

    public float[] R = {1, 0, 0, 0, 1, 0, 0, 0, 1};
    public float f = 1500;
    public Estacio est = new Estacio();
    public float[] pendent;                     // base d'un objecte esperant el cim
    public boolean actiu = false;
    public Toc toc;

    private final Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);

    public Overlay(Context c) { super(c); setWillNotDraw(false); }

    float dp(float v) { return v * getResources().getDisplayMetrics().density; }

    @Override
    public boolean onTouchEvent(MotionEvent e) {
        if (!actiu) return false;
        if (e.getAction() == MotionEvent.ACTION_UP && toc != null) toc.alToc(e.getX(), e.getY());
        return true;
    }

    @Override
    protected void onDraw(Canvas c) {
        if (!actiu) return;
        float W = getWidth(), H = getHeight(), cx = W / 2, cy = H / 2;
        // horitzó
        float v0 = Geo.horitzoV(R, f, cx, cy, 0), v1 = Geo.horitzoV(R, f, cx, cy, W);
        p.setStyle(Paint.Style.STROKE);
        p.setStrokeWidth(dp(2));
        p.setColor(Color.YELLOW);
        if (!Float.isNaN(v0) && !Float.isNaN(v1)) c.drawLine(0, v0, W, v1, p);
        // creu
        p.setColor(Color.WHITE);
        p.setStrokeWidth(dp(1.5f));
        c.drawLine(cx - dp(14), cy, cx + dp(14), cy, p);
        c.drawLine(cx, cy - dp(14), cx, cy + dp(14), p);
        // base d'objecte pendent: avisa
        if (pendent != null) {
            p.setStyle(Paint.Style.FILL);
            p.setTextSize(dp(14));
            c.drawText("toca ara el CIM de l'objecte", dp(10), dp(24), p);
        }
        dibuixaPla(c, W);
    }

    void dibuixaPla(Canvas c, float W) {
        float mida = dp(170), x0 = W - mida - dp(8), y0 = dp(8), cx = x0 + mida / 2, cy = y0 + mida / 2;
        p.setStyle(Paint.Style.FILL);
        p.setColor(0x99000000);
        c.drawRect(x0, y0, x0 + mida, y0 + mida, p);
        float rmax = 3f;
        for (float[] q : est.cant) rmax = Math.max(rmax, (float) Math.hypot(q[0], q[1]));
        for (float[] q : est.obj) rmax = Math.max(rmax, (float) Math.hypot(q[0], q[1]));
        float s = (mida / 2 - dp(6)) / (rmax * 1.1f);                     // px per metre
        p.setStyle(Paint.Style.STROKE);
        p.setStrokeWidth(dp(1));
        p.setColor(0x66FFFFFF);
        for (int m = 1; m <= rmax; m++) c.drawCircle(cx, cy, m * s, p);
        // polígon de cantonades (nord amunt)
        p.setColor(Color.CYAN);
        p.setStrokeWidth(dp(2));
        for (int i = 1; i < est.cant.size(); i++) {
            float[] a = est.cant.get(i - 1), b = est.cant.get(i);
            c.drawLine(cx + a[0] * s, cy - a[1] * s, cx + b[0] * s, cy - b[1] * s, p);
        }
        p.setStyle(Paint.Style.FILL);
        for (float[] q : est.cant) c.drawCircle(cx + q[0] * s, cy - q[1] * s, dp(3), p);
        p.setColor(Color.GREEN);
        p.setTextSize(dp(10));
        for (float[] q : est.obj) {
            c.drawRect(cx + q[0] * s - dp(3), cy - q[1] * s - dp(3), cx + q[0] * s + dp(3), cy - q[1] * s + dp(3), p);
            c.drawText(String.format("%.0f", q[2] * 100), cx + q[0] * s + dp(5), cy - q[1] * s, p);
        }
        // càmera i direcció (el centre del píxel és el raig -z del dispositiu)
        float fx = -R[2], fy = -R[5];
        float n = (float) Math.hypot(fx, fy);
        p.setColor(Color.WHITE);
        c.drawCircle(cx, cy, dp(3), p);
        if (n > 1e-3f) {
            p.setStyle(Paint.Style.STROKE);
            p.setStrokeWidth(dp(2));
            c.drawLine(cx, cy, cx + fx / n * dp(24), cy - fy / n * dp(24), p);
        }
    }
}
