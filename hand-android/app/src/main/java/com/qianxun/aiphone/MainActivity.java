package com.qianxun.aiphone;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.text.InputType;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

/** 设置页：填服务器地址、配对码，去系统里打开无障碍；显示连接状态。 */
public class MainActivity extends Activity {
    static final String DEFAULT_SERVER = "http://100.89.17.124:8700";

    private TextView status;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final Runnable refresh = new Runnable() {
        @Override public void run() {
            status.setText(HandService.instance == null
                    ? "未开启：点下面按钮，在无障碍里打开「AI 手」"
                    : "已开启 · " + HandService.status);
            ui.postDelayed(this, 1000);
        }
    };

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        SharedPreferences cfg = getSharedPreferences("cfg", MODE_PRIVATE);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        int pad = (int) (20 * getResources().getDisplayMetrics().density);
        root.setPadding(pad, pad * 2, pad, pad);

        TextView title = new TextView(this);
        title.setText("AI 手 · 让 AI 大脑替你操作手机");
        title.setTextSize(20);
        root.addView(title);

        root.addView(label("服务器地址"));
        EditText server = new EditText(this);
        server.setSingleLine();
        server.setText(cfg.getString("server", DEFAULT_SERVER));
        root.addView(server);

        root.addView(label("配对码"));
        EditText code = new EditText(this);
        code.setSingleLine();
        code.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        code.setText(cfg.getString("code", ""));
        root.addView(code);

        Button save = new Button(this);
        save.setText("保存");
        save.setOnClickListener(v -> {
            cfg.edit().putString("server", server.getText().toString().trim())
                    .putString("code", code.getText().toString().trim()).apply();
            status.setText("已保存");
        });
        root.addView(save);

        Button a11y = new Button(this);
        a11y.setText("打开无障碍设置");
        a11y.setOnClickListener(v -> startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)));
        root.addView(a11y);

        status = new TextView(this);
        status.setPadding(0, pad, 0, 0);
        root.addView(status, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        setContentView(root);
    }

    private TextView label(String s) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setPadding(0, 24, 0, 0);
        return t;
    }

    @Override protected void onResume() { super.onResume(); ui.post(refresh); }
    @Override protected void onPause() { super.onPause(); ui.removeCallbacks(refresh); }
}
