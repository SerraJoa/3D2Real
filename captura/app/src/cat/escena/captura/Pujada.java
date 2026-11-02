package cat.escena.captura;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.RandomAccessFile;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Puja una sessió de captura per HTTPS a `servidor/pujada.php`, en trossos i reprenent allà on s'havia quedat.
 * Només fa servir java.* (cap API d'Android) perquè es pugui provar amb un JVM normal.
 * Protocol: vegeu la capçalera de pujada.php.
 */
public final class Pujada {
    public interface Progres { void alt(String text); }

    public static final class Config {
        public final String url, token;
        public Config(String url, String token) { this.url = url; this.token = token; }

        /** Llegeix {"url": "...", "token": "..."} d'un fitxer petit (sense dependre de org.json). */
        public static Config llegeix(File f) throws IOException {
            String s = new String(java.nio.file.Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8);
            String u = camp(s, "url"), t = camp(s, "token");
            if (u == null || t == null) throw new IOException(f.getName() + ": falta «url» o «token»");
            if (!u.startsWith("https://") && !u.startsWith("http://127.0.0.1") && !u.startsWith("http://localhost"))
                throw new IOException("la URL ha de ser https");
            return new Config(u, t);
        }
        private static String camp(String json, String nom) {
            Matcher m = Pattern.compile("\"" + nom + "\"\\s*:\\s*\"([^\"]*)\"").matcher(json);
            return m.find() ? m.group(1) : null;
        }
    }

    static final int TROS = 4 * 1024 * 1024;
    static final String[] EXT = {".mp4", ".csv", ".json"};

    private final Config cfg;
    private final Progres pr;
    private volatile boolean cancela = false;

    public Pujada(Config cfg, Progres pr) { this.cfg = cfg; this.pr = pr; }

    public void cancela() { cancela = true; }

    /** Fitxers de la sessió que es pugen (els que el servidor accepta). */
    static List<File> fitxers(File dir) {
        List<File> out = new ArrayList<>();
        File[] tots = dir.listFiles();
        if (tots == null) return out;
        java.util.Arrays.sort(tots);
        for (File f : tots) {
            String n = f.getName().toLowerCase();
            for (String e : EXT) if (f.isFile() && n.endsWith(e)) { out.add(f); break; }
        }
        return out;
    }

    static String sha256(File f) throws IOException {
        try (InputStream in = new FileInputStream(f)) {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] b = new byte[1 << 16];
            int k;
            while ((k = in.read(b)) > 0) md.update(b, 0, k);
            StringBuilder sb = new StringBuilder();
            for (byte x : md.digest()) sb.append(String.format("%02x", x));
            return sb.toString();
        } catch (java.security.NoSuchAlgorithmException e) { throw new IOException(e); }
    }

    private static final class Resp { int codi; String cos; }

    private Resp post(String query, byte[] cos, int off, int len, String tipus) throws IOException {
        HttpURLConnection c = (HttpURLConnection) new URL(cfg.url + (cfg.url.contains("?") ? "&" : "?") + query).openConnection();
        c.setRequestMethod("POST");
        c.setConnectTimeout(15000);
        c.setReadTimeout(60000);
        c.setDoOutput(true);
        c.setFixedLengthStreamingMode(len);
        c.setRequestProperty("X-Token", cfg.token);
        c.setRequestProperty("Content-Type", tipus);
        try (OutputStream o = c.getOutputStream()) { o.write(cos, off, len); }
        Resp r = new Resp();
        r.codi = c.getResponseCode();
        InputStream in = r.codi < 400 ? c.getInputStream() : c.getErrorStream();
        StringBuilder sb = new StringBuilder();
        if (in != null) try (InputStream i = in) { byte[] b = new byte[4096]; int k; while ((k = i.read(b)) > 0) sb.append(new String(b, 0, k, StandardCharsets.UTF_8)); }
        r.cos = sb.toString();
        c.disconnect();
        return r;
    }

    private static long enter(String json, String camp) {
        Matcher m = Pattern.compile("\"" + Pattern.quote(camp) + "\"\\s*:\\s*(\\d+)").matcher(json);
        return m.find() ? Long.parseLong(m.group(1)) : -1;
    }

    /** Puja tota la sessió. Retorna el nombre de bytes enviats en aquesta crida (0 si ja hi era tot). */
    public long puja(File dir) throws IOException {
        String sessio = dir.getName();
        List<File> fs = fitxers(dir);
        if (fs.isEmpty()) throw new IOException("la sessió no té fitxers per pujar");
        StringBuilder man = new StringBuilder("{\"sessio\":\"" + sessio + "\",\"fitxers\":[");
        long total = 0;
        for (int i = 0; i < fs.size(); i++) {
            pr.alt("Calculant sha256 de " + fs.get(i).getName() + "…");
            man.append(i > 0 ? "," : "").append("{\"nom\":\"").append(fs.get(i).getName()).append("\",\"mida\":")
               .append(fs.get(i).length()).append(",\"sha256\":\"").append(sha256(fs.get(i))).append("\"}");
            total += fs.get(i).length();
        }
        man.append("]}");
        byte[] mb = man.toString().getBytes(StandardCharsets.UTF_8);
        Resp ini = post("a=inici", mb, 0, mb.length, "application/json");
        if (ini.codi != 200) throw new IOException("servidor: " + ini.codi + " " + ini.cos);

        long enviats = 0, fet = 0;
        byte[] buf = new byte[TROS];
        for (File f : fs) {
            long off = enter(ini.cos.substring(Math.max(0, ini.cos.indexOf("\"" + f.getName() + "\""))), f.getName());
            if (off < 0) off = 0;
            fet += off;
            try (RandomAccessFile raf = new RandomAccessFile(f, "r")) {
                int intents = 0;
                while (off < f.length()) {
                    if (cancela) throw new IOException("cancel·lada");
                    raf.seek(off);
                    int n = raf.read(buf, 0, (int) Math.min(TROS, f.length() - off));
                    try {
                        Resp r = post("a=tros&sessio=" + sessio + "&nom=" + f.getName() + "&offset=" + off, buf, 0, n, "application/octet-stream");
                        if (r.codi == 200) {
                            off += n; fet += n; enviats += n; intents = 0;
                            pr.alt(String.format("Pujant %s: %d%% (%d de %d MB)", f.getName(), total == 0 ? 100 : fet * 100 / total, fet >> 20, total >> 20));
                        } else if (r.codi == 409) {
                            long esperat = enter(r.cos, "esperat");
                            if (esperat < 0 || esperat == off) throw new IOException("servidor: " + r.codi + " " + r.cos);
                            fet += esperat - off; off = esperat;                         // es resincronitza amb el que té el servidor
                        } else throw new IOException("servidor: " + r.codi + " " + r.cos);
                    } catch (java.net.SocketException | java.net.SocketTimeoutException | java.net.UnknownHostException e) {
                        if (++intents > 5) throw e;
                        try { Thread.sleep(1500L * intents); } catch (InterruptedException ie) { throw new IOException("interromput"); }
                    }
                }
            }
        }
        Resp fi = post("a=fi&sessio=" + sessio, new byte[0], 0, 0, "application/octet-stream");
        if (fi.codi != 200) throw new IOException("servidor: " + fi.codi + " " + fi.cos);
        pr.alt("Sessió " + sessio + " pujada (" + (total >> 20) + " MB).");
        return enviats;
    }

    /** Prova des de la línia d'ordres: java Pujada <url> <token> <carpeta de sessió>. */
    public static void main(String[] a) throws Exception {
        long n = new Pujada(new Config(a[0], a[1]), System.out::println).puja(new File(a[2]));
        System.out.println("enviats " + n + " bytes");
    }
}
