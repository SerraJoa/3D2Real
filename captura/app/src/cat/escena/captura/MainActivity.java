package cat.escena.captura;

import android.Manifest;
import android.app.Activity;
import android.content.pm.PackageManager;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.graphics.Color;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.hardware.camera2.CameraAccessException;
import android.hardware.camera2.CameraCaptureSession;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraDevice;
import android.hardware.camera2.CameraManager;
import android.hardware.camera2.CaptureRequest;
import android.hardware.camera2.CaptureResult;
import android.hardware.camera2.TotalCaptureResult;
import android.hardware.camera2.params.ColorSpaceTransform;
import android.hardware.camera2.params.RggbChannelVector;
import android.hardware.camera2.params.StreamConfigurationMap;
import android.media.MediaRecorder;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.SystemClock;
import android.util.Range;
import android.util.Size;
import android.view.Gravity;
import android.view.Surface;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.View;
import android.view.WindowManager;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.Spinner;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedWriter;
import java.io.File;
import java.io.FileWriter;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Date;
import java.util.List;
import java.util.Locale;

/**
 * Captura per a l'escena 3D: prepara la càmera perquè el SfM rendeixi.
 * - estabilització i correcció de distorsió OFF (les intrínseques han de ser constants)
 * - "Fixa": exposició curta manual (menys moviment), enfocament i balanç de blancs congelats
 * - registra IMU (gir, acceleració, orientació) i metadades per fotograma amb temps comú
 * - enumera totes les òptiques que el mòbil exposa (cameras.json)
 */
public class MainActivity extends Activity implements SurfaceHolder.Callback {
    static final long OBTURADOR_MAX_NS = 4_000_000L;       // 1/250 s
    static final int ISO_MAX = 3200;
    static final int PREV_W = 1280, PREV_H = 720;

    CameraManager cm;
    SurfaceView sv;
    TextView info;
    Spinner spCam;
    Button btnFix, btnRec, btnRes, btnCal, btnPuja;
    Posicio pos;
    boolean locOk = false, pujant = false;
    Pujada pujada;
    HandlerThread ht;
    Handler h;
    CameraDevice dev;
    CameraCaptureSession sess;
    CameraCharacteristics cc;
    String camId;
    final List<String> ids = new ArrayList<>();
    List<Size> resols = new ArrayList<>();
    int resIdx = 0;
    boolean surfOk = false, permOk = false, canviantCam = false;

    boolean fixat = false;
    long fixT;
    int fixISO;
    float fixFoc;
    RggbChannelVector fixGains;
    ColorSpaceTransform fixXform;

    volatile long lastT;
    volatile int lastISO;
    volatile float lastFoc;
    volatile RggbChannelVector lastGains;
    volatile ColorSpaceTransform lastXform;
    volatile float[] lastIntr;
    int comptaFrames = 0;

    // mapa en directe (IMU + alçada de la càmera + terra)
    Overlay ov;
    LinearLayout filaMapa;
    Button btnMapa, btnModus, btnDesf, btnEst, btnHm, btnHp, btnCopia;
    boolean mapa = false;
    int modus = 0;                                   // 0 cantonada de terra, 1 objecte (base + cim)
    float alcadaCam = 1.40f;
    float fPx = 1500;
    final float[] rotM = new float[9];
    final List<Overlay.Estacio> estacions = new ArrayList<>();
    final SensorEventListener rotL = new SensorEventListener() {
        @Override public void onSensorChanged(SensorEvent e) {
            SensorManager.getRotationMatrixFromVector(rotM, e.values);
            System.arraycopy(rotM, 0, ov.R, 0, 9);
            calibraSensor();
            ov.invalidate();
        }
        @Override public void onAccuracyChanged(Sensor s, int a) { }
    };

    // mode calibratge (ChArUco): exposició/focus fixos + guia de cobertura d'orientacions amb l'IMU
    static final float CALIB_QUADRAT_MM = 29.07f;            // costat del quadrat IMPRÈS i mesurat (nominal 30 mm); es desa al meta.json
    boolean calib = false;
    float[] calD0, calUp;
    float calRoll0;
    int calMask = 0;
    String calTxt = "";
    static final String[] CAL_NOMS = {"centre", "esquerra", "dreta", "amunt", "avall", "gir+", "gir-"};

    MediaRecorder mr;
    String videoInfo = "";
    volatile boolean rec = false;
    File sessDir;
    BufferedWriter framesW, imuW;
    SensorManager sm;
    long t0Rec;

    // ---------------------------------------------------------------- cicle de vida
    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        cm = (CameraManager) getSystemService(CAMERA_SERVICE);
        sm = (SensorManager) getSystemService(SENSOR_SERVICE);
        ht = new HandlerThread("cam");
        ht.start();
        h = new Handler(ht.getLooper());
        construeixUI();
        enumera();
        permOk = checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED;
        locOk = checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED;
        if (!permOk || !locOk) requestPermissions(new String[]{Manifest.permission.CAMERA, Manifest.permission.ACCESS_FINE_LOCATION}, 1);
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] p, int[] r) {
        for (int i = 0; i < p.length && i < r.length; i++) {
            if (p[i].equals(Manifest.permission.CAMERA)) permOk = r[i] == PackageManager.PERMISSION_GRANTED;
            if (p[i].equals(Manifest.permission.ACCESS_FINE_LOCATION)) locOk = r[i] == PackageManager.PERMISSION_GRANTED;
        }
        if (permOk) { if (surfOk) obre(); }
        else missatge("Cal el permís de càmera");
    }

    @Override
    protected void onPause() {
        sm.unregisterListener(rotL);
        if (rec) paraGravacio();
        tanca();
        super.onPause();
    }

    @Override
    protected void onResume() {
        super.onResume();
        Sensor rv = sm.getDefaultSensor(Sensor.TYPE_GAME_ROTATION_VECTOR);
        if (rv != null) sm.registerListener(rotL, rv, SensorManager.SENSOR_DELAY_GAME);
        if (surfOk && permOk) obre();
    }

    @Override public void surfaceCreated(SurfaceHolder holder) { surfOk = true; if (permOk) obre(); }
    @Override public void surfaceChanged(SurfaceHolder holder, int f, int w, int hh) { }
    @Override public void surfaceDestroyed(SurfaceHolder holder) { surfOk = false; tanca(); }

    // ---------------------------------------------------------------- UI
    int dp(int v) { return Math.round(v * getResources().getDisplayMetrics().density); }

    Button boto(String t, View.OnClickListener l) {
        Button x = new Button(this);
        x.setText(t);
        x.setAllCaps(false);
        x.setOnClickListener(l);
        return x;
    }

    void construeixUI() {
        FrameLayout arrel = new FrameLayout(this);
        arrel.setBackgroundColor(Color.BLACK);
        sv = new SurfaceView(this);
        sv.getHolder().setFixedSize(PREV_W, PREV_H);
        sv.getHolder().addCallback(this);
        int ample = getResources().getDisplayMetrics().widthPixels;
        arrel.addView(sv, new FrameLayout.LayoutParams(ample, ample * 16 / 9, Gravity.TOP));
        ov = new Overlay(this);
        ov.toc = this::tocat;
        arrel.addView(ov, new FrameLayout.LayoutParams(ample, ample * 16 / 9, Gravity.TOP));
        estacions.add(ov.est);

        LinearLayout panell = new LinearLayout(this);
        panell.setOrientation(LinearLayout.VERTICAL);
        panell.setBackgroundColor(0xAA000000);
        panell.setPadding(dp(8), dp(6), dp(8), dp(8));

        info = new TextView(this);
        info.setTextColor(Color.WHITE);
        info.setTextSize(11);
        info.setTypeface(android.graphics.Typeface.MONOSPACE);
        panell.addView(info);

        spCam = new Spinner(this);
        ArrayAdapter<String> ad = new ArrayAdapter<>(this, android.R.layout.simple_spinner_item, etiquetes());
        ad.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        spCam.setAdapter(ad);
        spCam.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override public void onItemSelected(AdapterView<?> p, View v, int pos, long id) {
                String nou = ids.get(pos);
                if (!nou.equals(camId)) { camId = nou; fixat = false; actualitzaBotons(); tanca(); if (surfOk && permOk) obre(); }
            }
            @Override public void onNothingSelected(AdapterView<?> p) { }
        });
        panell.addView(spCam);

        LinearLayout fila = new LinearLayout(this);
        fila.setOrientation(LinearLayout.HORIZONTAL);
        btnFix = boto("Fixa", v -> alternaFix());
        btnRes = boto("1080p", v -> canviaResolucio());
        btnRec = boto("REC", v -> { if (rec) paraGravacio(); else iniciaGravacio(); });
        btnCal = boto("Calibra", v -> alternaCalibratge());
        btnPuja = boto("Puja", v -> pujaUltima());
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f);
        fila.addView(btnFix, lp);
        fila.addView(btnRes, lp);
        fila.addView(btnCal, lp);
        fila.addView(btnPuja, lp);
        fila.addView(btnRec, lp);
        panell.addView(fila);

        filaMapa = new LinearLayout(this);
        filaMapa.setOrientation(LinearLayout.HORIZONTAL);
        btnMapa = boto("Mapa", v -> alternaMapa());
        btnModus = boto("Cantonada", v -> { modus = 1 - modus; ov.pendent = null; actualitzaMapaUI(); });
        btnDesf = boto("Desfés", v -> desfes());
        btnEst = boto("Estació+", v -> novaEstacio());
        btnHm = boto("H−", v -> canviaH(-0.05f));
        btnHp = boto("H+", v -> canviaH(+0.05f));
        btnCopia = boto("Copia càmeres", v -> copiaCameres());
        for (Button b : new Button[]{btnMapa, btnModus, btnDesf, btnEst, btnHm, btnHp, btnCopia}) {
            b.setTextSize(11);
            b.setPadding(0, 0, 0, 0);
            filaMapa.addView(b, lp);
        }
        for (Button b : new Button[]{btnModus, btnDesf, btnEst, btnHm, btnHp}) b.setVisibility(View.GONE);
        panell.addView(filaMapa);

        FrameLayout.LayoutParams pl = new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.WRAP_CONTENT, Gravity.BOTTOM);
        arrel.addView(panell, pl);
        setContentView(arrel);
    }

    String nota = "";
    void missatge(String s) {
        nota = s;
        runOnUiThread(() -> { info.setText(s); android.widget.Toast.makeText(this, s, android.widget.Toast.LENGTH_LONG).show(); });
    }

    void actualitzaBotons() {
        runOnUiThread(() -> {
            btnFix.setText(fixat ? "Allibera" : "Fixa");
            btnRec.setText(rec ? "STOP" : "REC");
            btnCal.setText(calib ? (rec ? "Atura calib." : "Calibra: inicia") : "Calibra");
            btnRec.setEnabled(!calib);
            btnPuja.setText(pujant ? "Atura" : "Puja");
            btnPuja.setEnabled(!rec);
            btnRes.setEnabled(!rec);
            spCam.setEnabled(!rec);
            if (!resols.isEmpty()) btnRes.setText(resols.get(resIdx).getHeight() + "p");
        });
    }

    // ---------------------------------------------------------------- òptiques
    static boolean conte(int[] v, int x) {
        if (v == null) return false;
        for (int a : v) if (a == x) return true;
        return false;
    }

    List<String> etiquetes() {
        List<String> r = new ArrayList<>();
        for (String id : ids) {
            try {
                CameraCharacteristics c = cm.getCameraCharacteristics(id);
                float[] f = c.get(CameraCharacteristics.LENS_INFO_AVAILABLE_FOCAL_LENGTHS);
                android.util.SizeF s = c.get(CameraCharacteristics.SENSOR_INFO_PHYSICAL_SIZE);
                double fov = (f != null && s != null) ? Math.toDegrees(2 * Math.atan(s.getWidth() / (2 * f[0]))) : 0;
                Integer cara = c.get(CameraCharacteristics.LENS_FACING);
                r.add("id " + id + (cara != null && cara == CameraCharacteristics.LENS_FACING_BACK ? " darrere" : " davant")
                        + (f != null ? String.format(Locale.US, "  f=%.1f mm  FOV %.0f°", f[0], fov) : ""));
            } catch (CameraAccessException e) { r.add("id " + id); }
        }
        return r;
    }

    /** Llista totes les òptiques (lògiques i físiques) i les desa a cameras.json. */
    void enumera() {
        JSONArray arr = new JSONArray();
        try {
            for (String id : cm.getCameraIdList()) {
                CameraCharacteristics c = cm.getCameraCharacteristics(id);
                JSONObject o = new JSONObject();
                o.put("id", id);
                Integer cara = c.get(CameraCharacteristics.LENS_FACING);
                o.put("cara", cara == null ? -1 : cara);
                float[] f = c.get(CameraCharacteristics.LENS_INFO_AVAILABLE_FOCAL_LENGTHS);
                if (f != null) o.put("focals_mm", new JSONArray(toList(f)));
                android.util.SizeF s = c.get(CameraCharacteristics.SENSOR_INFO_PHYSICAL_SIZE);
                if (s != null) o.put("sensor_mm", new JSONArray(new double[]{s.getWidth(), s.getHeight()}));
                Size pix = c.get(CameraCharacteristics.SENSOR_INFO_PIXEL_ARRAY_SIZE);
                if (pix != null) o.put("pixels", new JSONArray(new int[]{pix.getWidth(), pix.getHeight()}));
                Float mf = c.get(CameraCharacteristics.LENS_INFO_MINIMUM_FOCUS_DISTANCE);
                if (mf != null) o.put("focus_min_dioptries", mf);
                Integer so = c.get(CameraCharacteristics.SENSOR_ORIENTATION);
                if (so != null) o.put("orientacio_sensor", so);
                Integer ts = c.get(CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE);
                if (ts != null) o.put("font_temps", ts == CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE_REALTIME ? "REALTIME" : "UNKNOWN");
                int[] caps = c.get(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES);
                if (caps != null) o.put("capacitats", new JSONArray(caps));
                o.put("fisiques", new JSONArray(new ArrayList<>(c.getPhysicalCameraIds())));
                o.put("ois", conte(c.get(CameraCharacteristics.LENS_INFO_AVAILABLE_OPTICAL_STABILIZATION), 1));
                arr.put(o);
                if (cara != null && cara == CameraCharacteristics.LENS_FACING_BACK) ids.add(id);
            }
            if (ids.isEmpty()) ids.addAll(java.util.Arrays.asList(cm.getCameraIdList()));
            camId = ids.isEmpty() ? null : ids.get(0);
            File d = getExternalFilesDir(null);
            try (FileWriter w = new FileWriter(new File(d, "cameras.json"))) { w.write(arr.toString(2)); }
        } catch (Exception e) { missatge("Error enumerant: " + e); }
    }

    static List<Double> toList(float[] f) {
        List<Double> l = new ArrayList<>();
        for (float x : f) l.add((double) x);
        return l;
    }

    // ---------------------------------------------------------------- càmera
    void obre() {
        if (camId == null || dev != null || canviantCam) return;
        try {
            cc = cm.getCameraCharacteristics(camId);
            carregaResolucions();
            calculaF();
            canviantCam = true;
            cm.openCamera(camId, new CameraDevice.StateCallback() {
                @Override public void onOpened(CameraDevice d) { dev = d; canviantCam = false; arrencaSessio(false); }
                @Override public void onDisconnected(CameraDevice d) { d.close(); dev = null; canviantCam = false; }
                @Override public void onError(CameraDevice d, int e) { d.close(); dev = null; canviantCam = false; missatge("Error càmera " + e); }
            }, h);
        } catch (SecurityException | CameraAccessException e) { canviantCam = false; missatge("No puc obrir: " + e); }
    }

    void tanca() {
        try { if (sess != null) sess.close(); } catch (Exception ignorat) { }
        sess = null;
        try { if (dev != null) dev.close(); } catch (Exception ignorat) { }
        dev = null;
    }

    void carregaResolucions() {
        resols = new ArrayList<>();
        StreamConfigurationMap m = cc.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP);
        if (m != null) {
            for (Size s : m.getOutputSizes(MediaRecorder.class)) {
                if (s.getWidth() * 9 == s.getHeight() * 16 && (s.getWidth() == 1920 || s.getWidth() == 3840)) resols.add(s);
            }
        }
        if (resols.isEmpty()) resols.add(new Size(1920, 1080));
        Collections.sort(resols, (a, b) -> a.getWidth() - b.getWidth());
        resIdx = 0;
        for (int i = 0; i < resols.size(); i++) if (resols.get(i).getWidth() == 1920) resIdx = i;
        actualitzaBotons();
    }

    void canviaResolucio() {
        resIdx = (resIdx + 1) % resols.size();
        actualitzaBotons();
    }

    /** Paràmetres comuns de la petició: res d'estabilització ni de correcció, i el mode fix si toca. */
    void aplica(CaptureRequest.Builder rb) {
        if (conte(cc.get(CameraCharacteristics.CONTROL_AVAILABLE_VIDEO_STABILIZATION_MODES), CaptureRequest.CONTROL_VIDEO_STABILIZATION_MODE_OFF))
            rb.set(CaptureRequest.CONTROL_VIDEO_STABILIZATION_MODE, CaptureRequest.CONTROL_VIDEO_STABILIZATION_MODE_OFF);
        if (conte(cc.get(CameraCharacteristics.LENS_INFO_AVAILABLE_OPTICAL_STABILIZATION), CaptureRequest.LENS_OPTICAL_STABILIZATION_MODE_OFF))
            rb.set(CaptureRequest.LENS_OPTICAL_STABILIZATION_MODE, CaptureRequest.LENS_OPTICAL_STABILIZATION_MODE_OFF);
        if (conte(cc.get(CameraCharacteristics.DISTORTION_CORRECTION_AVAILABLE_MODES), CaptureRequest.DISTORTION_CORRECTION_MODE_OFF))
            rb.set(CaptureRequest.DISTORTION_CORRECTION_MODE, CaptureRequest.DISTORTION_CORRECTION_MODE_OFF);
        Range<Integer>[] fps = cc.get(CameraCharacteristics.CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES);
        if (fps != null) for (Range<Integer> r : fps) if (r.getLower() == 30 && r.getUpper() == 30) rb.set(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE, r);

        if (!fixat) {
            rb.set(CaptureRequest.CONTROL_AE_MODE, CaptureRequest.CONTROL_AE_MODE_ON);
            rb.set(CaptureRequest.CONTROL_AWB_MODE, CaptureRequest.CONTROL_AWB_MODE_AUTO);
            if (conte(cc.get(CameraCharacteristics.CONTROL_AF_AVAILABLE_MODES), CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_VIDEO))
                rb.set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_VIDEO);
            return;
        }
        rb.set(CaptureRequest.CONTROL_AE_MODE, CaptureRequest.CONTROL_AE_MODE_OFF);
        rb.set(CaptureRequest.SENSOR_EXPOSURE_TIME, fixT);
        rb.set(CaptureRequest.SENSOR_SENSITIVITY, fixISO);
        rb.set(CaptureRequest.SENSOR_FRAME_DURATION, 33_333_333L);
        Float minFoc = cc.get(CameraCharacteristics.LENS_INFO_MINIMUM_FOCUS_DISTANCE);
        if (minFoc != null && minFoc > 0) {
            rb.set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_OFF);
            rb.set(CaptureRequest.LENS_FOCUS_DISTANCE, fixFoc);
        }
        if (conte(cc.get(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES),
                CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_MANUAL_POST_PROCESSING) && fixGains != null && fixXform != null) {
            rb.set(CaptureRequest.CONTROL_AWB_MODE, CaptureRequest.CONTROL_AWB_MODE_OFF);
            rb.set(CaptureRequest.COLOR_CORRECTION_MODE, CaptureRequest.COLOR_CORRECTION_MODE_TRANSFORM_MATRIX);
            rb.set(CaptureRequest.COLOR_CORRECTION_GAINS, fixGains);
            rb.set(CaptureRequest.COLOR_CORRECTION_TRANSFORM, fixXform);
        } else {
            rb.set(CaptureRequest.CONTROL_AWB_LOCK, true);
        }
    }

    void arrencaSessio(boolean gravant) {
        if (dev == null) return;
        try {
            if (sess != null) { sess.close(); sess = null; }
            final Surface ps = sv.getHolder().getSurface();
            final List<Surface> outs = new ArrayList<>();
            outs.add(ps);
            if (gravant) outs.add(mr.getSurface());
            dev.createCaptureSession(outs, new CameraCaptureSession.StateCallback() {
                @Override public void onConfigured(CameraCaptureSession s) {
                    sess = s;
                    try {
                        CaptureRequest.Builder rb = dev.createCaptureRequest(gravant ? CameraDevice.TEMPLATE_RECORD : CameraDevice.TEMPLATE_PREVIEW);
                        rb.addTarget(ps);
                        if (gravant) rb.addTarget(mr.getSurface());
                        aplica(rb);
                        s.setRepeatingRequest(rb.build(), cb, h);
                        if (gravant) { t0Rec = SystemClock.elapsedRealtimeNanos(); mr.start(); rec = true; actualitzaBotons(); }
                    } catch (Exception e) { missatge("Sessió: " + e); }
                }
                @Override public void onConfigureFailed(CameraCaptureSession s) { missatge("No puc configurar la sessió"); }
            }, h);
        } catch (Exception e) { missatge("Sessió: " + e); }
    }

    final CameraCaptureSession.CaptureCallback cb = new CameraCaptureSession.CaptureCallback() {
        @Override public void onCaptureCompleted(CameraCaptureSession s, CaptureRequest r, TotalCaptureResult res) {
            Long t = res.get(CaptureResult.SENSOR_EXPOSURE_TIME);
            Integer iso = res.get(CaptureResult.SENSOR_SENSITIVITY);
            Float foc = res.get(CaptureResult.LENS_FOCUS_DISTANCE);
            if (t != null) lastT = t;
            if (iso != null) lastISO = iso;
            if (foc != null) lastFoc = foc;
            RggbChannelVector g = res.get(CaptureResult.COLOR_CORRECTION_GAINS);
            ColorSpaceTransform x = res.get(CaptureResult.COLOR_CORRECTION_TRANSFORM);
            if (g != null) lastGains = g;
            if (x != null) lastXform = x;
            float[] intr = res.get(CaptureResult.LENS_INTRINSIC_CALIBRATION);
            if (intr != null) lastIntr = intr;
            Long ts = res.get(CaptureResult.SENSOR_TIMESTAMP);
            BufferedWriter w = framesW;
            if (rec && w != null && ts != null) {
                try {
                    synchronized (w) {
                        w.write(ts + "," + res.getFrameNumber() + "," + (t == null ? "" : t) + "," + (iso == null ? "" : iso) + ","
                                + (foc == null ? "" : foc) + "\n");
                    }
                } catch (Exception ignorat) { }
            }
            if (++comptaFrames % 10 == 0) mostra();
        }
    };

    void mostra() {
        final String s = String.format(Locale.US, "%s  %s%s\nobturador 1/%.0f  ISO %d  focus %.2f D\n%s",
                camId, resols.isEmpty() ? "" : resols.get(resIdx).getWidth() + "x" + resols.get(resIdx).getHeight(),
                fixat ? "  [FIX]" : "  [auto]",
                lastT > 0 ? 1e9 / lastT : 0, lastISO, lastFoc,
                (rec ? String.format(Locale.US, "REC %.0f s", (SystemClock.elapsedRealtimeNanos() - t0Rec) / 1e9) : "") + "\n" + nota + (calib ? "\n" + calTxt : ""));
        runOnUiThread(() -> info.setText(s));
    }

    /** Copia cameras.json al porta-retalls per poder-lo enganxar a un xat. */
    void copiaCameres() {
        try {
            File f = new File(getExternalFilesDir(null), "cameras.json");
            byte[] b = java.nio.file.Files.readAllBytes(f.toPath());
            String t = new String(b, java.nio.charset.StandardCharsets.UTF_8);
            ((ClipboardManager) getSystemService(CLIPBOARD_SERVICE)).setPrimaryClip(ClipData.newPlainText("cameras.json", t));
            missatge("cameras.json copiat (" + t.length() + " caràcters): enganxa'l al xat");
        } catch (Exception e) { missatge("No puc copiar: " + e); }
    }

    // ---------------------------------------------------------------- mapa en directe
    void calculaF() {
        float[] f = cc.get(CameraCharacteristics.LENS_INFO_AVAILABLE_FOCAL_LENGTHS);
        android.util.SizeF sz = cc.get(CameraCharacteristics.SENSOR_INFO_PHYSICAL_SIZE);
        if (f == null || sz == null) return;
        float altVista = getResources().getDisplayMetrics().widthPixels * 16f / 9f;       // el costat llarg de la vista = amplada horitzontal del sensor
        fPx = f[0] / sz.getWidth() * altVista;
        ov.f = fPx;
    }

    void alternaMapa() {
        mapa = !mapa;
        ov.actiu = mapa;
        ov.pendent = null;
        int vis = mapa ? View.VISIBLE : View.GONE;
        for (Button b : new Button[]{btnModus, btnDesf, btnEst, btnHm, btnHp}) b.setVisibility(vis);
        btnMapa.setText(mapa ? "Mapa ON" : "Mapa");
        actualitzaMapaUI();
        ov.invalidate();
    }

    void actualitzaMapaUI() {
        btnModus.setText(modus == 0 ? "Cantonada" : "Objecte");
        btnHm.setText(String.format(Locale.US, "H−"));
        btnHp.setText(String.format(Locale.US, "H+"));
        missatge(String.format(Locale.US, "Mapa: alçada càmera %.2f m · f=%.0f px · estació %d · %d cantonades · %d objectes",
                alcadaCam, fPx, estacions.size(), ov.est.cant.size(), ov.est.obj.size()));
    }

    void canviaH(float d) {
        alcadaCam = Math.max(0.3f, Math.min(2.2f, alcadaCam + d));
        actualitzaMapaUI();
        desaMapa();
    }

    void novaEstacio() {
        ov.est = new Overlay.Estacio();
        estacions.add(ov.est);
        ov.pendent = null;
        actualitzaMapaUI();
        ov.invalidate();
        desaMapa();
    }

    void desfes() {
        if (ov.pendent != null) ov.pendent = null;
        else if (modus == 1 && !ov.est.obj.isEmpty()) ov.est.obj.remove(ov.est.obj.size() - 1);
        else if (!ov.est.cant.isEmpty()) ov.est.cant.remove(ov.est.cant.size() - 1);
        actualitzaMapaUI();
        ov.invalidate();
        desaMapa();
    }

    void tocat(float u, float v) {
        float W = ov.getWidth(), Hh = ov.getHeight();
        float[] r = Geo.raig(rotM, fPx, W / 2, Hh / 2, u, v);
        if (modus == 0 || ov.pendent == null) {
            float[] q = Geo.terra(r, alcadaCam);
            if (q == null) { missatge("Apunta més cap al terra (la base ha de tocar el terra)"); return; }
            if (modus == 0) ov.est.cant.add(q);
            else ov.pendent = new float[]{q[0], q[1], (float) Math.hypot(q[0], q[1])};
        } else {
            float alt = Geo.alcadaSobreBase(r, alcadaCam, ov.pendent[2]);
            if (Float.isNaN(alt) || alt <= 0) { missatge("El cim ha de quedar per sobre del terra"); return; }
            ov.est.obj.add(new float[]{ov.pendent[0], ov.pendent[1], alt});
            ov.pendent = null;
        }
        actualitzaMapaUI();
        ov.invalidate();
        desaMapa();
    }

    /** Desa tot el mapa a files/espai.json (s'actualitza a cada toc; es recull amb adb pull). */
    void desaMapa() {
        try {
            JSONObject o = new JSONObject();
            o.put("alcada_camera_m", alcadaCam);
            o.put("f_px_vista", fPx);
            o.put("nota", "x est, y nord (yaw arbitrari: GAME_ROTATION_VECTOR); cada estació té origen propi; punts en m respecte de la càmera");
            JSONArray es = new JSONArray();
            for (Overlay.Estacio e : estacions) {
                JSONObject eo = new JSONObject();
                JSONArray c = new JSONArray(), ob = new JSONArray();
                for (float[] q : e.cant) c.put(new JSONArray(new double[]{q[0], q[1]}));
                for (float[] q : e.obj) ob.put(new JSONArray(new double[]{q[0], q[1], q[2]}));
                eo.put("cantonades_terra", c);
                eo.put("objectes_x_y_alcada", ob);
                es.put(eo);
            }
            o.put("estacions", es);
            try (FileWriter w = new FileWriter(new File(getExternalFilesDir(null), "espai.json"))) { w.write(o.toString(2)); }
        } catch (Exception e) { missatge("No puc desar el mapa: " + e); }
    }

    // ---------------------------------------------------------------- fixar exposició / focus / blancs
    void alternaFix() {
        if (rec) return;
        if (fixat) { fixat = false; calib = false; calTxt = ""; }
        else {
            if (lastT <= 0 || lastISO <= 0) { missatge("Encara no hi ha mesura, espera un segon"); return; }
            long t = lastT;
            int iso = lastISO;
            if (t > OBTURADOR_MAX_NS) {                       // exposició curta: compensa amb ISO fins al topall
                double k = (double) t / OBTURADOR_MAX_NS;
                int isoNou = (int) Math.min(ISO_MAX, Math.round(iso * k));
                Range<Integer> rang = cc.get(CameraCharacteristics.SENSOR_INFO_SENSITIVITY_RANGE);
                if (rang != null) isoNou = Math.max(rang.getLower(), Math.min(rang.getUpper(), isoNou));
                t = Math.round((double) lastT * iso / isoNou);   // manté la mateixa exposició total: t·ISO constant
                t = Math.min(t, lastT);
                iso = isoNou;
            }
            fixT = t; fixISO = iso; fixFoc = lastFoc; fixGains = lastGains; fixXform = lastXform;
            fixat = true;
        }
        actualitzaBotons();
        arrencaSessio(false);
    }

    // ---------------------------------------------------------------- calibratge ChArUco
    /** 1r toc: fixa exposició+focus (apunta al tauler perquè enfoqui). 2n toc: comença a gravar. 3r: atura. */
    void alternaCalibratge() {
        if (!calib) {
            calib = true;
            if (!fixat) alternaFix();
            calMask = 0; calD0 = null;
            calTxt = "Tauler pla, il·luminació difusa, sense reflexos.\nEnquadra'l i prem 'Calibra: inicia'.";
            actualitzaBotons();
            return;
        }
        if (!rec) {
            if (!fixat) { missatge("Espera: encara no s'ha fixat l'exposició"); return; }
            calMask = 0; calD0 = null;
            iniciaGravacio();
            return;
        }
        paraGravacio();
        calib = false;
        calTxt = "";
        actualitzaBotons();
    }

    static float[] norm(float[] v) {
        float n = (float) Math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
        return n < 1e-6f ? v : new float[]{v[0] / n, v[1] / n, v[2] / n};
    }
    static float[] cr(float[] a, float[] b) { return new float[]{a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]}; }
    static float dt(float[] a, float[] b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }

    /** Gir de la càmera al voltant de l'eix òptic, mesurat amb l'eix X del dispositiu sobre un pla perpendicular a l'eix. */
    float rollDe(float[] d, float[] x) {
        float[] u = norm(cr(calUp, d)), v = cr(d, u);
        return (float) Math.toDegrees(Math.atan2(dt(x, v), dt(x, u)));
    }

    /** Marca quines orientacions ja s'han cobert respecte de la primera (el tauler es considera enfront). */
    void calibraSensor() {
        if (!calib || !rec) return;
        float[] R = rotM;
        float[] d = {-R[2], -R[5], -R[8]};                 // eix òptic al món (Z amunt)
        float[] x = {R[0], R[3], R[6]};                    // eix X del dispositiu al món
        if (calD0 == null) {
            calD0 = d.clone();
            calUp = Math.abs(d[2]) < 0.9f ? new float[]{0, 0, 1} : new float[]{0, 1, 0};
            calRoll0 = rollDe(d, x);
        }
        float[] e1 = norm(cr(calD0, calUp)), e2 = cr(e1, calD0);
        float c = dt(d, calD0);
        double az = Math.toDegrees(Math.atan2(dt(d, e1), c)), el = Math.toDegrees(Math.atan2(dt(d, e2), c));
        double gir = rollDe(d, x) - calRoll0;
        while (gir > 180) gir -= 360;
        while (gir < -180) gir += 360;
        if (Math.abs(az) < 8 && Math.abs(el) < 8) calMask |= 1;
        if (az < -15) calMask |= 2;
        if (az > 15) calMask |= 4;
        if (el > 15) calMask |= 8;
        if (el < -15) calMask |= 16;
        if (gir > 30) calMask |= 32;
        if (gir < -30) calMask |= 64;
        StringBuilder sb = new StringBuilder("Cobertura:");
        int n = 0;
        for (int i = 0; i < CAL_NOMS.length; i++) {
            boolean ok = (calMask & (1 << i)) != 0;
            if (ok) n++;
            sb.append(' ').append(ok ? "[x]" : "[ ]").append(CAL_NOMS[i]);
        }
        sb.append(String.format(Locale.US, "  %d/7\nIncl. 15-30° cap a cada costat, gira 30°+. Fes-ho a 2 distàncies. Lent (sense moviment).", n));
        calTxt = sb.toString();
    }

    // ---------------------------------------------------------------- gravació + IMU
    final SensorEventListener imu = new SensorEventListener() {
        @Override public void onSensorChanged(SensorEvent e) {
            BufferedWriter w = imuW;
            if (!rec || w == null) return;
            int tipus = e.sensor.getType();
            StringBuilder sb = new StringBuilder().append(e.timestamp).append(',').append(tipus);
            for (int i = 0; i < e.values.length && i < 4; i++) sb.append(',').append(e.values[i]);
            sb.append('\n');
            try { synchronized (w) { w.write(sb.toString()); } } catch (Exception ignorat) { }
        }
        @Override public void onAccuracyChanged(Sensor s, int a) { }
    };

    void iniciaGravacio() {
        if (dev == null || rec) return;
        try {
            Size mida = resols.get(resIdx);
            sessDir = new File(getExternalFilesDir("sessions"), new SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(new Date()));
            sessDir.mkdirs();
            framesW = new BufferedWriter(new FileWriter(new File(sessDir, "frames.csv")));
            framesW.write("sensor_timestamp_ns,frame,exposicio_ns,iso,focus_dioptries\n");
            imuW = new BufferedWriter(new FileWriter(new File(sessDir, "imu.csv")));
            imuW.write("timestamp_ns,tipus,v0,v1,v2,v3\n");   // tipus 1 acc, 4 gir, 15 game_rotation_vector (x,y,z,w)
            pos = new Posicio(this);
            pos.inicia(new File(sessDir, "posicio.csv"), locOk);

            // el codificador de maquinari pot no acceptar 4K amb aquest bitrat/còdec: es proven combinacions fins que prepare() passa
            int[] kbps = mida.getWidth() >= 3840 ? new int[]{60, 40, 25} : new int[]{30, 20};
            int[] cods = mida.getWidth() >= 3840 ? new int[]{MediaRecorder.VideoEncoder.H264, MediaRecorder.VideoEncoder.HEVC} : new int[]{MediaRecorder.VideoEncoder.H264};
            String errs = "";
            mr = null;
            for (int cod : cods) {
                for (int k : kbps) {
                    try {
                        mr = new MediaRecorder();
                        mr.setVideoSource(MediaRecorder.VideoSource.SURFACE);
                        mr.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4);
                        mr.setOutputFile(new File(sessDir, "video.mp4").getAbsolutePath());
                        mr.setVideoEncodingBitRate(k * 1_000_000);
                        mr.setVideoFrameRate(30);
                        mr.setVideoSize(mida.getWidth(), mida.getHeight());
                        mr.setVideoEncoder(cod);
                        Integer so = cc.get(CameraCharacteristics.SENSOR_ORIENTATION);
                        mr.setOrientationHint(so == null ? 90 : so);
                        mr.prepare();
                        videoInfo = (cod == MediaRecorder.VideoEncoder.HEVC ? "HEVC " : "H264 ") + k + " Mbps";
                        break;
                    } catch (Exception e) {
                        errs += (cod == MediaRecorder.VideoEncoder.HEVC ? "HEVC " : "H264 ") + k + "M: " + e.getMessage() + "\n";
                        try { mr.release(); } catch (Exception ignorat) { }
                        mr = null;
                    }
                }
                if (mr != null) break;
            }
            if (mr == null) throw new java.io.IOException("cap combinació " + mida.getWidth() + "x" + mida.getHeight() + " accepta prepare():\n" + errs);

            for (int t : new int[]{Sensor.TYPE_ACCELEROMETER, Sensor.TYPE_GYROSCOPE, Sensor.TYPE_GAME_ROTATION_VECTOR}) {
                Sensor s = sm.getDefaultSensor(t);
                if (s != null) sm.registerListener(imu, s, SensorManager.SENSOR_DELAY_FASTEST, h);
            }
            arrencaSessio(true);
        } catch (Exception e) { missatge("No puc gravar: " + e); netejaGravacio(); }
    }

    void paraGravacio() {
        if (!rec) return;
        rec = false;
        sm.unregisterListener(imu);
        // la sessió ha de tancar-se abans de mr.stop(): si encara alimenta la superfície, stop() falla i el mp4 queda sense moov
        try { if (sess != null) { sess.stopRepeating(); sess.close(); sess = null; } } catch (Exception ignorat) { }
        String err = "";
        try { mr.stop(); } catch (Exception e) { err = " (stop ha fallat: " + e + ")"; }
        if (pos != null) pos.atura();
        escriuMeta();
        netejaGravacio();
        actualitzaBotons();
        arrencaSessio(false);
        long mb = new File(sessDir, "video.mp4").length() / (1024 * 1024);
        missatge("Vídeo " + mb + " MB " + videoInfo + err + ". Copiant a Descàrregues/escena…");
        exportaPublic(sessDir, mb, err);
    }

    /** Copia la sessió a Descàrregues/escena/<sessió>/ (visible al gestor de fitxers i per USB), sense permisos des d'Android 10. */
    void exportaPublic(final File dir, final long mb, final String err) {
        new Thread(() -> {
            try {
                if (Build.VERSION.SDK_INT < 29) { missatge("Android < 10: fitxers només a " + dir); return; }
                int n = 0;
                for (File f : dir.listFiles()) {
                    android.content.ContentValues v = new android.content.ContentValues();
                    v.put(android.provider.MediaStore.MediaColumns.DISPLAY_NAME, f.getName());
                    v.put(android.provider.MediaStore.MediaColumns.RELATIVE_PATH, "Download/escena/" + dir.getName());
                    android.net.Uri u = getContentResolver().insert(android.provider.MediaStore.Downloads.EXTERNAL_CONTENT_URI, v);
                    try (java.io.InputStream in = new java.io.FileInputStream(f); java.io.OutputStream out = getContentResolver().openOutputStream(u)) {
                        byte[] b = new byte[1 << 16];
                        int k;
                        while ((k = in.read(b)) > 0) out.write(b, 0, k);
                    }
                    n++;
                }
                missatge("Vídeo " + mb + " MB " + videoInfo + err + ". Copiats " + n + " fitxers a Descàrregues/escena/" + dir.getName());
            } catch (Exception e) { missatge("Còpia a Descàrregues ha fallat: " + e + "\nFitxers a " + dir); }
        }).start();
    }

    /** Puja l'última sessió gravada a l'adreça de files/pujada.json ({"url": "https://…/pujada.php", "token": "…"}). */
    void pujaUltima() {
        if (pujant) { if (pujada != null) pujada.cancela(); return; }
        File[] ss = getExternalFilesDir("sessions").listFiles(File::isDirectory);
        if (ss == null || ss.length == 0) { missatge("Cap sessió gravada."); return; }
        java.util.Arrays.sort(ss);
        final File dir = ss[ss.length - 1];
        final Pujada.Config cfg;
        try { cfg = Pujada.Config.llegeix(new File(getExternalFilesDir(null), "pujada.json")); }
        catch (Exception e) { missatge("Configura files/pujada.json: " + e.getMessage()); return; }
        pujant = true; actualitzaBotons();
        pujada = new Pujada(cfg, this::missatge);
        new Thread(() -> {
            try { pujada.puja(dir); }
            catch (Exception e) { missatge("La pujada s'ha aturat: " + e.getMessage() + ". Torna a prémer Puja per continuar."); }
            pujant = false; actualitzaBotons();
        }).start();
    }

    void netejaGravacio() {
        try { if (mr != null) { mr.reset(); mr.release(); } } catch (Exception ignorat) { }
        mr = null;
        try { if (framesW != null) { synchronized (framesW) { framesW.close(); } } } catch (Exception ignorat) { }
        try { if (imuW != null) { synchronized (imuW) { imuW.close(); } } } catch (Exception ignorat) { }
        framesW = null; imuW = null;
    }

    void escriuMeta() {
        try {
            JSONObject o = new JSONObject();
            o.put("model", Build.MODEL);
            o.put("camera_id", camId);
            Size m = resols.get(resIdx);
            o.put("mida", new JSONArray(new int[]{m.getWidth(), m.getHeight()}));
            o.put("fps", 30);
            o.put("codec", videoInfo);
            o.put("mode_fix", fixat);
            if (calib) {
                o.put("calibratge", true);
                o.put("quadrat_mm", CALIB_QUADRAT_MM);
                o.put("tauler", "ChArUco 5x7, DICT_5X5_100, marcador 22/30 del quadrat");
                o.put("cobertura_imu", calMask);
            }
            if (fixat) {
                o.put("exposicio_ns", fixT);
                o.put("iso", fixISO);
                o.put("focus_dioptries", fixFoc);
            }
            Integer ts = cc.get(CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE);
            o.put("font_temps_camera", ts != null && ts == CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE_REALTIME ? "REALTIME" : "UNKNOWN");
            o.put("nota_temps", "imu.timestamp i sensor_timestamp comparteixen rellotge només si REALTIME");
            Integer so = cc.get(CameraCharacteristics.SENSOR_ORIENTATION);
            o.put("orientacio_sensor", so);
            float[] f = cc.get(CameraCharacteristics.LENS_INFO_AVAILABLE_FOCAL_LENGTHS);
            if (f != null) o.put("focal_mm", f[0]);
            android.util.SizeF sz = cc.get(CameraCharacteristics.SENSOR_INFO_PHYSICAL_SIZE);
            if (sz != null) o.put("sensor_mm", new JSONArray(new double[]{sz.getWidth(), sz.getHeight()}));
            if (lastIntr != null) o.put("intrinseques_fx_fy_cx_cy_s", new JSONArray(toList(lastIntr)));
            android.graphics.Rect act = cc.get(CameraCharacteristics.SENSOR_INFO_ACTIVE_ARRAY_SIZE);
            if (act != null) o.put("matriu_activa", new JSONArray(new int[]{act.width(), act.height()}));
            if (pos != null) pos.alMeta(o);
            o.put("inici_elapsed_ns", t0Rec);
            o.put("durada_s", (SystemClock.elapsedRealtimeNanos() - t0Rec) / 1e9);
            try (FileWriter w = new FileWriter(new File(sessDir, "meta.json"))) { w.write(o.toString(2)); }
        } catch (Exception e) { missatge("meta: " + e); }
    }
}
