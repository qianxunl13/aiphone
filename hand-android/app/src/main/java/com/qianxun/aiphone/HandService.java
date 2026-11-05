package com.qianxun.aiphone;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.ResolveInfo;
import android.graphics.Bitmap;
import android.graphics.Path;
import android.graphics.Rect;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.util.Base64;
import android.util.DisplayMetrics;
import android.view.Display;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import android.view.accessibility.AccessibilityWindowInfo;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/**
 * 「手」：开无障碍后常驻，向大脑服务器长轮询取指令，执行后回传结果。
 * 指令：observe / screenshot / tap / swipe / click_text / type / global / launch / open_url / apps
 */
public class HandService extends AccessibilityService {
    static volatile HandService instance;
    static volatile String status = "启动中";
    private volatile boolean running;
    private final String device = (Build.MANUFACTURER + "-" + Build.MODEL).replace(' ', '_');

    @Override
    protected void onServiceConnected() {
        instance = this;
        running = true;
        new Thread(this::loop, "hand-loop").start();
    }

    @Override public void onAccessibilityEvent(AccessibilityEvent e) { }
    @Override public void onInterrupt() { }

    @Override
    public void onDestroy() {
        running = false;
        instance = null;
        super.onDestroy();
    }

    // ---------- 与大脑通信 ----------

    private void loop() {
        while (running) {
            SharedPreferences cfg = getSharedPreferences("cfg", MODE_PRIVATE);
            String server = cfg.getString("server", MainActivity.DEFAULT_SERVER).replaceAll("/+$", "");
            String code = cfg.getString("code", "");
            try {
                String q = "?device=" + URLEncoder.encode(device, "UTF-8") + "&code=" + URLEncoder.encode(code, "UTF-8");
                HttpURLConnection c = (HttpURLConnection) new URL(server + "/hand/poll" + q).openConnection();
                c.setConnectTimeout(8000);
                c.setReadTimeout(40000);
                int rc = c.getResponseCode();
                if (rc == 204) { status = "已连上大脑，等待指令"; continue; }
                if (rc == 401) { status = "配对码不对"; sleep(5000); continue; }
                if (rc != 200) { status = "服务器返回 " + rc; sleep(3000); continue; }
                JSONObject cmd = new JSONObject(read(c.getInputStream()));
                status = "执行：" + cmd.optString("action");
                JSONObject res;
                try {
                    res = run(cmd);
                } catch (Exception ex) {
                    res = new JSONObject().put("ok", false).put("error", ex.toString());
                }
                res.put("id", cmd.optString("id"));
                post(server + "/hand/result" + q, res);
                status = "已连上大脑，刚做完：" + cmd.optString("action");
            } catch (Exception ex) {
                status = "连不上服务器：" + ex.getClass().getSimpleName() + " " + ex.getMessage();
                sleep(3000);
            }
        }
    }

    private static String read(InputStream in) throws Exception {
        ByteArrayOutputStream bo = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n;
        while ((n = in.read(buf)) > 0) bo.write(buf, 0, n);
        return bo.toString("UTF-8");
    }

    private static void post(String url, JSONObject body) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        c.setConnectTimeout(8000);
        c.setReadTimeout(20000);
        c.setDoOutput(true);
        c.setRequestMethod("POST");
        c.setRequestProperty("Content-Type", "application/json");
        try (OutputStream o = c.getOutputStream()) { o.write(body.toString().getBytes(StandardCharsets.UTF_8)); }
        c.getResponseCode();
    }

    private static void sleep(long ms) {
        try { Thread.sleep(ms); } catch (InterruptedException ignored) { }
    }

    // ---------- 执行指令 ----------

    private JSONObject run(JSONObject cmd) throws Exception {
        String a = cmd.optString("action");
        JSONObject r = new JSONObject().put("ok", true);
        switch (a) {
            case "observe":
                return observe(r);
            case "screenshot":
                return screenshot(r, cmd.optInt("width", 540));
            case "tap":
                return r.put("ok", gesture(cmd.getInt("x"), cmd.getInt("y"), cmd.getInt("x"), cmd.getInt("y"), 60));
            case "swipe":
                return r.put("ok", gesture(cmd.getInt("x1"), cmd.getInt("y1"), cmd.getInt("x2"), cmd.getInt("y2"),
                        cmd.optInt("ms", 300)));
            case "click_text":
                return clickText(r, cmd.getString("text"));
            case "type":
                return type(r, cmd.getString("text"));
            case "global":
                return r.put("ok", performGlobalAction(globalCode(cmd.getString("name"))));
            case "launch": {
                Intent i = getPackageManager().getLaunchIntentForPackage(cmd.getString("package"));
                if (i == null) return r.put("ok", false).put("error", "没装这个 App");
                i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                startActivity(i);
                return r;
            }
            case "open_url": {
                Intent i = new Intent(Intent.ACTION_VIEW, Uri.parse(cmd.getString("url")));
                i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                startActivity(i);
                return r;
            }
            case "apps":
                return apps(r);
            default:
                return r.put("ok", false).put("error", "不认识的指令：" + a);
        }
    }

    private int globalCode(String name) {
        switch (name) {
            case "home": return GLOBAL_ACTION_HOME;
            case "recents": return GLOBAL_ACTION_RECENTS;
            case "notifications": return GLOBAL_ACTION_NOTIFICATIONS;
            default: return GLOBAL_ACTION_BACK;
        }
    }

    /** 读屏：把所有窗口里有字、可点、可输入、可滚动的控件列出来（带坐标）。 */
    private JSONObject observe(JSONObject r) throws Exception {
        DisplayMetrics dm = getResources().getDisplayMetrics();
        r.put("screen", new JSONArray().put(dm.widthPixels).put(dm.heightPixels));
        JSONArray nodes = new JSONArray();
        List<AccessibilityNodeInfo> roots = roots();
        AccessibilityNodeInfo active = getRootInActiveWindow();
        if (active != null) r.put("package", String.valueOf(active.getPackageName()));
        for (AccessibilityNodeInfo root : roots) walk(root, nodes, 0);
        r.put("windows", roots.size());
        return r.put("nodes", nodes);
    }

    private List<AccessibilityNodeInfo> roots() {
        List<AccessibilityNodeInfo> out = new ArrayList<>();
        java.util.Set<Integer> ids = new java.util.HashSet<>();
        try {
            for (AccessibilityWindowInfo w : getWindows()) {
                AccessibilityNodeInfo n = w.getRoot();
                if (n != null) { out.add(n); ids.add(w.getId()); }
            }
        } catch (Exception ignored) { }
        // getWindows() 有时只返回状态栏等系统窗口、漏掉前台 App ⇒ 永远把当前活动窗口也带上
        AccessibilityNodeInfo active = getRootInActiveWindow();
        if (active != null && !ids.contains(active.getWindowId())) out.add(active);
        return out;
    }

    private void walk(AccessibilityNodeInfo n, JSONArray out, int depth) throws Exception {
        if (n == null || depth > 60 || out.length() >= 500) return;
        CharSequence t = n.getText(), d = n.getContentDescription();
        boolean useful = (t != null && t.length() > 0) || (d != null && d.length() > 0)
                || n.isClickable() || n.isEditable() || n.isScrollable();
        if (useful && n.isVisibleToUser()) {
            Rect b = new Rect();
            n.getBoundsInScreen(b);
            JSONObject o = new JSONObject();
            if (t != null && t.length() > 0) o.put("t", trim(t));
            if (d != null && d.length() > 0) o.put("d", trim(d));
            String id = n.getViewIdResourceName();
            if (id != null) o.put("id", id.substring(id.indexOf('/') + 1));
            if (n.isClickable()) o.put("c", 1);
            if (n.isEditable()) o.put("e", 1);
            if (n.isScrollable()) o.put("s", 1);
            o.put("b", new JSONArray().put(b.left).put(b.top).put(b.right).put(b.bottom));
            out.put(o);
        }
        for (int i = 0; i < n.getChildCount(); i++) walk(n.getChild(i), out, depth + 1);
    }

    private static String trim(CharSequence s) {
        String x = s.toString().replace('\n', ' ');
        return x.length() > 120 ? x.substring(0, 120) + "…" : x;
    }

    private JSONObject screenshot(JSONObject r, int width) throws Exception {
        if (Build.VERSION.SDK_INT < 30) return r.put("ok", false).put("error", "安卓 11 以下不支持截图");
        CountDownLatch done = new CountDownLatch(1);
        final String[] b64 = {null};
        final String[] err = {null};
        takeScreenshot(Display.DEFAULT_DISPLAY, getMainExecutor(), new TakeScreenshotCallback() {
            @Override public void onSuccess(ScreenshotResult s) {
                try {
                    Bitmap hw = Bitmap.wrapHardwareBuffer(s.getHardwareBuffer(), s.getColorSpace());
                    Bitmap bmp = hw.copy(Bitmap.Config.ARGB_8888, false);
                    s.getHardwareBuffer().close();
                    int h = bmp.getHeight() * width / bmp.getWidth();
                    Bitmap small = Bitmap.createScaledBitmap(bmp, width, h, true);
                    ByteArrayOutputStream bo = new ByteArrayOutputStream();
                    small.compress(Bitmap.CompressFormat.JPEG, 60, bo);
                    b64[0] = Base64.encodeToString(bo.toByteArray(), Base64.NO_WRAP);
                } catch (Exception ex) { err[0] = ex.toString(); }
                done.countDown();
            }
            @Override public void onFailure(int code) { err[0] = "截图失败，错误码 " + code; done.countDown(); }
        });
        if (!done.await(10, TimeUnit.SECONDS)) return r.put("ok", false).put("error", "截图超时");
        if (err[0] != null) return r.put("ok", false).put("error", err[0]);
        return r.put("jpeg", b64[0]);
    }

    private boolean gesture(int x1, int y1, int x2, int y2, int ms) throws InterruptedException {
        Path p = new Path();
        p.moveTo(x1, y1);
        if (x1 != x2 || y1 != y2) p.lineTo(x2, y2);
        GestureDescription g = new GestureDescription.Builder()
                .addStroke(new GestureDescription.StrokeDescription(p, 0, Math.max(ms, 1))).build();
        CountDownLatch done = new CountDownLatch(1);
        final boolean[] ok = {false};
        boolean sent = dispatchGesture(g, new GestureResultCallback() {
            @Override public void onCompleted(GestureDescription d) { ok[0] = true; done.countDown(); }
            @Override public void onCancelled(GestureDescription d) { done.countDown(); }
        }, null);
        if (!sent) return false;
        done.await(ms + 3000L, TimeUnit.MILLISECONDS);
        return ok[0];
    }

    /** 按文字找控件点：优先点它（或可点的上级），不行就点它中心坐标。 */
    private JSONObject clickText(JSONObject r, String text) throws Exception {
        for (AccessibilityNodeInfo root : roots()) {
            AccessibilityNodeInfo hit = find(root, text);
            if (hit == null) continue;
            AccessibilityNodeInfo n = hit;
            while (n != null && !n.isClickable()) n = n.getParent();
            if (n != null && n.performAction(AccessibilityNodeInfo.ACTION_CLICK)) return r.put("how", "click");
            Rect b = new Rect();
            hit.getBoundsInScreen(b);
            return r.put("ok", gesture(b.centerX(), b.centerY(), b.centerX(), b.centerY(), 60)).put("how", "tap");
        }
        return r.put("ok", false).put("error", "屏幕上没找到：" + text);
    }

    private AccessibilityNodeInfo find(AccessibilityNodeInfo n, String text) {
        if (n == null) return null;
        CharSequence t = n.getText(), d = n.getContentDescription();
        if (n.isVisibleToUser() && ((t != null && t.toString().contains(text)) || (d != null && d.toString().contains(text))))
            return n;
        for (int i = 0; i < n.getChildCount(); i++) {
            AccessibilityNodeInfo hit = find(n.getChild(i), text);
            if (hit != null) return hit;
        }
        return null;
    }

    /** 往当前输入框里填字（没有焦点就找第一个输入框）。 */
    private JSONObject type(JSONObject r, String text) throws Exception {
        AccessibilityNodeInfo target = null;
        for (AccessibilityNodeInfo root : roots()) {
            target = root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT);
            if (target == null) target = firstEditable(root);
            if (target != null) break;
        }
        if (target == null) return r.put("ok", false).put("error", "没找到输入框");
        Bundle args = new Bundle();
        args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text);
        return r.put("ok", target.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args));
    }

    private AccessibilityNodeInfo firstEditable(AccessibilityNodeInfo n) {
        if (n == null) return null;
        if (n.isEditable() && n.isVisibleToUser()) return n;
        for (int i = 0; i < n.getChildCount(); i++) {
            AccessibilityNodeInfo hit = firstEditable(n.getChild(i));
            if (hit != null) return hit;
        }
        return null;
    }

    private JSONObject apps(JSONObject r) throws Exception {
        Intent main = new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER);
        JSONArray list = new JSONArray();
        for (ResolveInfo ri : getPackageManager().queryIntentActivities(main, 0)) {
            list.put(new JSONObject().put("name", String.valueOf(ri.loadLabel(getPackageManager())))
                    .put("package", ri.activityInfo.packageName));
        }
        return r.put("apps", list);
    }
}
