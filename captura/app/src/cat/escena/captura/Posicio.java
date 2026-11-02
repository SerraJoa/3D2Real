package cat.escena.captura;

import android.content.Context;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.os.Bundle;
import android.os.SystemClock;

import org.json.JSONObject;

import java.io.BufferedWriter;
import java.io.File;
import java.io.FileWriter;

/**
 * Registra GPS i brúixola (nord magnètic) durant la gravació a `posicio.csv`:
 *   timestamp_ns,tipus,v0,v1,v2,v3   —   gps: lat, lon, alt_m, precisio_m   ·   bruixola: azimut_graus, precisio_rad
 * El nord és el magnètic; la declinació (GeomagneticField) va al meta.json. Si no hi ha permís de
 * localització o sensor, no escriu res d'aquest tipus i la gravació continua igual.
 */
final class Posicio implements LocationListener, SensorEventListener {
    private final Context ctx;
    private BufferedWriter w;
    private LocationManager lm;
    private SensorManager sm;
    private Location primera;
    private long ultimaBruixola = 0;
    private final float[] r = new float[9], o = new float[3];

    Posicio(Context ctx) { this.ctx = ctx; }

    @SuppressWarnings("MissingPermission")
    void inicia(File csv, boolean permisLoc) {
        try {
            w = new BufferedWriter(new FileWriter(csv));
            w.write("timestamp_ns,tipus,v0,v1,v2,v3\n");
        } catch (Exception e) { w = null; return; }
        sm = (SensorManager) ctx.getSystemService(Context.SENSOR_SERVICE);
        Sensor rv = sm.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR);
        if (rv != null) sm.registerListener(this, rv, SensorManager.SENSOR_DELAY_NORMAL);
        if (permisLoc) {
            lm = (LocationManager) ctx.getSystemService(Context.LOCATION_SERVICE);
            try {
                if (lm.isProviderEnabled(LocationManager.GPS_PROVIDER)) lm.requestLocationUpdates(LocationManager.GPS_PROVIDER, 1000, 0, this);
                Location l = lm.getLastKnownLocation(LocationManager.GPS_PROVIDER);
                if (l != null) escriuGps(l);
            } catch (SecurityException | IllegalArgumentException ignorat) { lm = null; }
        }
    }

    void atura() {
        if (sm != null) sm.unregisterListener(this);
        if (lm != null) { try { lm.removeUpdates(this); } catch (SecurityException ignorat) { } }
        try { if (w != null) synchronized (this) { w.close(); } } catch (Exception ignorat) { }
        w = null;
    }

    /** Afegeix al meta.json la primera posició i la declinació magnètica, si n'hi ha. */
    void alMeta(JSONObject m) {
        try {
            if (primera == null) { m.put("gps", false); return; }
            m.put("gps", true);
            m.put("gps_inicial", new org.json.JSONArray(new double[]{primera.getLatitude(), primera.getLongitude(), primera.getAltitude(), primera.getAccuracy()}));
            android.hardware.GeomagneticField gf = new android.hardware.GeomagneticField(
                    (float) primera.getLatitude(), (float) primera.getLongitude(), (float) primera.getAltitude(), System.currentTimeMillis());
            m.put("declinacio_graus", gf.getDeclination());
            m.put("nord_nota", "posicio.csv: l'azimut de la brúixola és respecte del nord magnètic; sumar declinacio_graus per al geogràfic");
        } catch (Exception ignorat) { }
    }

    private synchronized void linia(String s) { try { if (w != null) w.write(s); } catch (Exception ignorat) { } }

    private void escriuGps(Location l) {
        if (primera == null) primera = l;
        linia(SystemClock.elapsedRealtimeNanos() + ",gps," + l.getLatitude() + "," + l.getLongitude() + "," + l.getAltitude() + "," + l.getAccuracy() + "\n");
    }

    @Override public void onLocationChanged(Location l) { escriuGps(l); }
    @Override public void onProviderEnabled(String p) { }
    @Override public void onProviderDisabled(String p) { }
    @Override public void onStatusChanged(String p, int s, Bundle b) { }

    @Override public void onSensorChanged(SensorEvent e) {
        long t = e.timestamp;
        if (t - ultimaBruixola < 500_000_000L) return;               // 2 mostres per segon n'hi ha prou
        ultimaBruixola = t;
        SensorManager.getRotationMatrixFromVector(r, e.values);
        SensorManager.getOrientation(r, o);                           // o[0] = azimut del mòbil (eix -z del telèfon)
        double az = (Math.toDegrees(o[0]) + 360) % 360;
        float prec = e.values.length > 4 ? e.values[4] : -1f;
        linia(t + ",bruixola," + az + "," + prec + ",,\n");
    }
    @Override public void onAccuracyChanged(Sensor s, int a) { }
}
