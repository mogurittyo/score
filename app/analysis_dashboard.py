import pandas as pd
from matplotlib.figure import Figure
import matplotlib.pyplot as plt # フォント設定などで必要になる場合がある
import numpy as np

# 日本語フォント設定の試み (環境依存)
# try:
#     plt.rcParams['font.family'] = 'sans-serif'
#     plt.rcParams['font.sans-serif'] = ['IPAexGothic', 'Yu Gothic UI', 'MS Gothic', 'Hiragino Sans', 'Noto Sans CJK JP']
# except Exception as e:
#     print(f"[AnalysisDashboard] Matplotlibフォント設定でエラー: {e}")

def create_score_histogram(df_scores, column_name='score_final', bins=20, title_suffix="Distribution"):
    fig = Figure(figsize=(6, 4), dpi=100)
    ax = fig.add_subplot(111)
    if df_scores is None or df_scores.empty or column_name not in df_scores.columns or df_scores[column_name].isnull().all():
        ax.text(0.5, 0.5, f"{column_name} のデータがありません", ha='center', va='center', transform=ax.transAxes, fontsize=10, color='gray')
    else:
        data_to_plot = df_scores[column_name].dropna()
        if data_to_plot.empty:
            ax.text(0.5, 0.5, f"{column_name} の有効なデータがありません", ha='center', va='center', transform=ax.transAxes, fontsize=10, color='gray')
        else:
            try:
                min_val, max_val = data_to_plot.min(), data_to_plot.max()
                # ビンエッジの調整: データが単一値の場合や範囲が狭い場合を考慮
                if min_val == max_val:
                    bin_edges = np.linspace(min_val - 0.5, max_val + 0.5, max(2, bins // 2)) # 最低2ビン
                elif max_val - min_val < bins : # 範囲がビン数より小さい場合、整数単位でビンを作る試み
                    bin_edges = np.arange(np.floor(min_val), np.ceil(max_val) + 1)
                    if len(bin_edges) < 2 : bin_edges = np.linspace(min_val, max_val, max(2,bins//2)) # それでもダメなら
                else:
                    bin_edges = np.linspace(min_val, max_val, bins + 1)

                ax.hist(data_to_plot, bins=bin_edges, color='cornflowerblue', edgecolor='black', alpha=0.75)
            except Exception as e:
                 ax.text(0.5, 0.5, f"ヒストグラム描画エラー:\n{e}", ha='center', va='center', transform=ax.transAxes, fontsize=9, color='red')
        ax.set_xlabel("スコア", fontsize=10); ax.set_ylabel("画像数", fontsize=10)
        ax.grid(axis='y', linestyle='--', alpha=0.6)
    ax.set_title(f"{column_name} {title_suffix}", fontsize=12, fontweight='bold')
    fig.tight_layout()
    return fig

def get_top_failure_tags(df_scores, top_n=30, column_name='failure_tags'):
    if df_scores is None or df_scores.empty or column_name not in df_scores.columns:
        return pd.Series(dtype='object') # object型で空のSeries
    
    # failure_tagsカラムがリストであることを期待。そうでない場合は空のリストとして扱う
    def _to_list_if_not(x):
        if isinstance(x, list): return x
        if pd.isna(x): return []
        return [] # または str(x).split(',') のような処理も考えられる

    processed_tags = df_scores[column_name].apply(_to_list_if_not)
    all_tags_series = processed_tags.explode().dropna() # NaNや空文字列を除去
    all_tags_series = all_tags_series[all_tags_series != ''] # 空文字列も除去

    if all_tags_series.empty: return pd.Series(dtype='object')
    return all_tags_series.value_counts().nlargest(top_n)

def create_failure_tags_barchart(df_scores, top_n=20, column_name='failure_tags'):
    fig = Figure(figsize=(7, 5), dpi=100)
    ax = fig.add_subplot(111)
    tag_counts = get_top_failure_tags(df_scores, top_n=top_n, column_name=column_name)
    if tag_counts.empty:
        ax.text(0.5, 0.5, "集計できるタグがありません", ha='center', va='center', transform=ax.transAxes, fontsize=10, color='gray')
    else:
        tag_counts.sort_values(ascending=True).plot(kind='barh', ax=ax, color='lightcoral', edgecolor='darkred')
        ax.set_xlabel("出現回数", fontsize=10); ax.set_ylabel("破綻タグ", fontsize=10)
        for i, (tag_name, v_count) in enumerate(tag_counts.sort_values(ascending=True).items()):
            ax.text(v_count + max(0.5, v_count*0.02), i, str(v_count), color='black', va='center', fontsize=8, fontweight='medium')
    ax.set_title(f"破綻タグ TOP {top_n}", fontsize=12, fontweight='bold')
    ax.grid(axis='x', linestyle=':', alpha=0.7)
    fig.tight_layout()
    return fig

if __name__ == '__main__':
    print("--- Analysis Dashboard Module Test ---")
    data_size = 200; np.random.seed(42)
    dummy_data = {
        'score_final': np.random.beta(a=5, b=2, size=data_size) * 10, # 0-10の範囲で偏った分布
        'failure_tags': [np.random.choice(['blurry', 'bad_anatomy', 'extra_fingers', 'text', 'cropped', None, []], p=[0.25,0.15,0.1,0.05,0.1,0.15,0.2], size=np.random.randint(0,4)).tolist() for _ in range(data_size)]
    }
    for i in range(data_size):
        if isinstance(dummy_data['failure_tags'][i], list): dummy_data['failure_tags'][i] = [t for t in dummy_data['failure_tags'][i] if t is not None and t != '']
        elif dummy_data['failure_tags'][i] is None: dummy_data['failure_tags'][i] = []
    df_test = pd.DataFrame(dummy_data)
    df_test['score_final'] = df_test['score_final'].round(2)
    
    hist_fig = create_score_histogram(df_test, 'score_final', bins=15)
    if hist_fig: hist_fig.savefig("test_score_histogram_final.png"); print("test_score_histogram_final.png 保存済")
    tags_fig = create_failure_tags_barchart(df_test, top_n=10)
    if tags_fig: tags_fig.savefig("test_failure_tags_barchart_final.png"); print("test_failure_tags_barchart_final.png 保存済")
    print("--- Analysis Dashboard Module Test End ---")

