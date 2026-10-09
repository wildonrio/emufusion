package com.thorium.preview.cheats;

import android.content.Context;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import com.thorium.lucent.cheats.CheatPanelSnapshot;

import java.util.ArrayList;
import java.util.List;

/**
 * Draws a {@link CheatPanelSnapshot} on the Thor's lower display while the game
 * runs above it.
 *
 * <p>Selection is painted, not focused. The window this lives in is
 * {@code FLAG_NOT_FOCUSABLE} so it can never take the pad away from the game,
 * which also means Android's focus machinery is unavailable here: the highlight
 * is a background the view sets itself, driven by the index in the snapshot.
 * Anything that relied on {@code requestFocus} would silently show no selection
 * at all.
 *
 * <p>Rows are still touchable, because the lower screen is a touchscreen and a
 * user reaching for a cheat will try to tap it. A tap reports the row index
 * back; it never changes what is drawn, since the game host owns the state and
 * publishes the result.
 */
public final class CheatPanelView extends FrameLayout {

    /** Reported to the game host, which owns the cheats and answers by redrawing. */
    public interface Listener {
        void onCheatRowTapped(int index);
        void onCloseTapped();
    }

    private static final int COLOR_ACCENT = Color.rgb(151, 119, 255);
    private static final int COLOR_ROW = Color.rgb(30, 30, 37);

    private final LinearLayout rows;
    private final ScrollView scroller;
    private final TextView title;
    private final TextView detail;
    private final TextView empty;
    private final List<View> rowViews = new ArrayList<>();
    private Listener listener;
    private int pageFirstIndex;

    public CheatPanelView(Context context) {
        super(context);
        setBackgroundColor(Color.rgb(6, 8, 12));
        // The panel is the whole lower screen rather than a floating card: it
        // is read at a glance while the eyes are really on the game above, and
        // a card would waste the width that makes a cheat name readable there.
        LinearLayout column = new LinearLayout(context);
        column.setOrientation(LinearLayout.VERTICAL);
        column.setPadding(dp(28), dp(22), dp(28), dp(20));

        title = new TextView(context);
        title.setTextColor(Color.WHITE);
        title.setTextSize(23f);
        title.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        column.addView(title, row(LinearLayout.LayoutParams.WRAP_CONTENT, 0));

        TextView heading = new TextView(context);
        heading.setText("Cheats");
        heading.setTextColor(COLOR_ACCENT);
        heading.setTextSize(14f);
        heading.setAllCaps(true);
        column.addView(heading, row(LinearLayout.LayoutParams.WRAP_CONTENT, 2));

        rows = new LinearLayout(context);
        rows.setOrientation(LinearLayout.VERTICAL);
        scroller = new ScrollView(context);
        scroller.setFillViewport(true);
        scroller.addView(rows, new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT));
        LinearLayout.LayoutParams scrollParams = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f);
        scrollParams.topMargin = dp(12);
        column.addView(scroller, scrollParams);

        empty = new TextView(context);
        empty.setTextColor(Color.argb(200, 255, 255, 255));
        empty.setTextSize(17f);
        empty.setGravity(Gravity.CENTER);
        empty.setVisibility(GONE);
        rows.addView(empty, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT));

        detail = new TextView(context);
        detail.setTextColor(Color.argb(190, 255, 255, 255));
        detail.setTextSize(14f);
        column.addView(detail, row(LinearLayout.LayoutParams.WRAP_CONTENT, 12));

        TextView hint = new TextView(context);
        hint.setText("D-pad moves  •  A toggles  •  B closes  •  " +
                "Select + L1 opens this from the game");
        hint.setTextColor(Color.argb(135, 255, 255, 255));
        hint.setTextSize(12f);
        hint.setOnClickListener(view -> {
            if (listener != null) listener.onCloseTapped();
        });
        column.addView(hint, row(LinearLayout.LayoutParams.WRAP_CONTENT, 8));

        addView(column, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT));
    }

    public void setListener(Listener next) { listener = next; }

    /**
     * Redraws for a new snapshot.
     *
     * <p>The row views are rebuilt only when the number of rows changes. A game
     * with a long list is republished on every D-pad step, and rebuilding the
     * tree each time would restart the ScrollView's position from the top.
     */
    public void render(CheatPanelSnapshot snapshot) {
        if (snapshot == null) return;
        pageFirstIndex = snapshot.firstIndex;
        title.setText(snapshot.title.isEmpty() ? "Game" : snapshot.title);
        if (rowViews.size() != snapshot.rows.size()) rebuild(snapshot);
        for (int index = 0; index < rowViews.size(); index++) {
            TextView view = (TextView) rowViews.get(index);
            CheatPanelSnapshot.Row entry = snapshot.rows.get(index);
            boolean selected = index == snapshot.selected;
            view.setText(entry.label());
            view.setTextColor(selected ? Color.WHITE : Color.argb(215, 255, 255, 255));
            GradientDrawable background = new GradientDrawable();
            background.setColor(selected ? COLOR_ACCENT : COLOR_ROW);
            background.setCornerRadius(dp(11));
            background.setStroke(dp(1), selected ? Color.WHITE
                    : Color.argb(70, 255, 255, 255));
            view.setBackground(background);
        }
        empty.setText(snapshot.message);
        empty.setVisibility(snapshot.isEmpty() ? VISIBLE : GONE);
        detail.setText(snapshot.detail());
        bringSelectionIntoView(snapshot.selected);
    }

    private void rebuild(CheatPanelSnapshot snapshot) {
        for (View view : rowViews) rows.removeView(view);
        rowViews.clear();
        for (int index = 0; index < snapshot.rows.size(); index++) {
            final int tapped = index;
            TextView view = new TextView(getContext());
            view.setTextSize(17f);
            view.setGravity(Gravity.CENTER_VERTICAL);
            view.setPadding(dp(16), 0, dp(16), 0);
            view.setOnClickListener(ignored -> {
                if (listener != null) listener.onCheatRowTapped(pageFirstIndex + tapped);
            });
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT, dp(54));
            params.topMargin = dp(8);
            rows.addView(view, params);
            rowViews.add(view);
        }
    }

    /**
     * Keeps the selected row on screen as the pad walks past the fold.
     *
     * <p>Posted rather than scrolled inline because a rebuilt row has no
     * measured top until the next layout pass, and scrolling to zero there
     * would jump the list back to the start on every reopen.
     */
    private void bringSelectionIntoView(int selected) {
        if (selected < 0 || selected >= rowViews.size()) return;
        final View target = rowViews.get(selected);
        scroller.post(() -> {
            int top = target.getTop();
            int bottom = top + target.getHeight();
            int visibleTop = scroller.getScrollY();
            int visibleBottom = visibleTop + scroller.getHeight();
            if (top < visibleTop) scroller.smoothScrollTo(0, Math.max(0, top - dp(8)));
            else if (bottom > visibleBottom)
                scroller.smoothScrollTo(0, bottom - scroller.getHeight() + dp(8));
        });
    }

    private LinearLayout.LayoutParams row(int height, int topMarginDp) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, height);
        params.topMargin = dp(topMarginDp);
        return params;
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }
}
