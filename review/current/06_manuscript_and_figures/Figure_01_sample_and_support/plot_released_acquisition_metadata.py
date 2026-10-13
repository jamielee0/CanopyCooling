"""Plot released acquisition metadata only. No model fit or thermal-array access."""
from pathlib import Path
import csv, json, sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.colors import Normalize

repo = Path(sys.argv[1])
source = repo / 'deliverables/Pilot_Results_Review_2023_v6_2_20261006/pilot_pass_summary.csv'
with source.open(newline='') as f:
    # Only acquisition and view metadata enter the plotted arrays.
    rows = [{k: r[k] for k in ['city', 'orbit', 'local_date', 'apparent_solar_hour', 'view_zenith_p95_deg']}
            for r in csv.DictReader(f)]
assert len(rows) == len({(r['city'], r['orbit']) for r in rows}) == 16
assert all(r['local_date'].startswith('2023-') for r in rows)
assert sum(r['city'] == 'phoenix' for r in rows) == 11
assert sum(r['city'] == 'atlanta' for r in rows) == 5
phoenix = [r for r in rows if r['city'] == 'phoenix']
assert {r['orbit'] for r in phoenix if float(r['view_zenith_p95_deg']) <= 15} == {'27963', '28024', '28706'}
assert not any(9.5 <= float(r['apparent_solar_hour']) <= 11.5 and float(r['view_zenith_p95_deg']) <= 15 for r in phoenix)

out = repo / 'review/current/06_manuscript_and_figures/Figure_01_sample_and_support'
out.mkdir(parents=True, exist_ok=True)
plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 12})
fig, axes = plt.subplots(1, 2, figsize=(13.5, 6), sharey=True, constrained_layout=False)
normalizer = Normalize(0, 25)
for ax, city in zip(axes, ['phoenix', 'atlanta']):
    ax.axvspan(9.5, 11.5, color='#dbece4', alpha=.8)
    ax.axvspan(15, 18, color='#f3e4d5', alpha=.8)
    selected = [r for r in rows if r['city'] == city]
    for row in selected:
        hour = float(row['apparent_solar_hour'])
        month = int(row['local_date'][5:7])
        angle = float(row['view_zenith_p95_deg'])
        ax.scatter(hour, month, c=[angle], cmap='viridis', norm=normalizer, s=100,
                   marker='o' if angle <= 15 else 'X', edgecolors='#203631', linewidths=.65)
        label = row['local_date'][8:10].lstrip('0')
        offset = (12, 10) if row['orbit'] == '27835' else (-12, 10) if row['orbit'] == '28145' else (0, 10)
        ax.annotate(label, (hour, month), xytext=offset, textcoords='offset points', ha='center', fontsize=11)
    ax.set(xlim=(9, 18.7), ylim=(9.55, 5.45), yticks=[6, 7, 8, 9], yticklabels=['June', 'July', 'August', 'September'],
           xticks=[9, 10.5, 12, 13.5, 15, 16.5, 18], xlabel='Apparent solar observation hour', title=city.title())
    ax.tick_params(labelleft=True)
    ax.grid(axis='y', color='#d7ddda', linewidth=.8)
    for side in ['top', 'right']:
        ax.spines[side].set_visible(False)
    ax.text(10.5, 5.65, 'Morning window', ha='center', fontsize=10, color='#345747')
    ax.text(16.5, 5.65, 'Afternoon window', ha='center', fontsize=10, color='#7c5035')

fig.subplots_adjust(left=.09, right=.87, bottom=.36, top=.83, wspace=.17)
fig.suptitle('2023 acquisition support and sensor-angle imbalance', x=.49, y=.97, fontsize=18, fontweight='bold')
cax = fig.add_axes([.9, .3, .015, .48])
bar = fig.colorbar(plt.cm.ScalarMappable(norm=normalizer, cmap='viridis'), cax=cax)
bar.set_label('Pass p95 view zenith (degrees)', fontsize=11)
fig.legend(handles=[Line2D([0], [0], marker='o', color='none', markerfacecolor='#52756a', markeredgecolor='#203631', markersize=8,
                           label='p95 view zenith ≤15°'),
                    Line2D([0], [0], marker='X', color='none', markerfacecolor='#52756a', markeredgecolor='#203631', markersize=8,
                           label='p95 view zenith >15°')], loc='lower center', bbox_to_anchor=(.46, .18), ncol=2, frameon=False)
fig.text(.09, .12, 'Labels show day of month. All 16 original acquisitions remain plotted. Marker classes are descriptive, not a new inclusion rule.', fontsize=10)
fig.text(.09, .078, 'Phoenix has no sampled July/September morning acquisition. All Phoenix morning passes have p95 view zenith >15°.', fontsize=10)
fig.text(.09, .036, 'Source: released acquisition table. These are observation metadata, not an empirical cooling or replication result.', fontsize=10)
fig.savefig(out / '01_dates_solar_time_and_sensor_angles.png', dpi=180)
fig.savefig(out / '01_dates_solar_time_and_sensor_angles.pdf')
plt.close(fig)
(out / 'plot_metadata.json').write_text(json.dumps({'source': str(source.relative_to(repo)), 'rows': 16,
    'phoenix_rows': 11, 'atlanta_rows': 5, 'phoenix_at_or_below_15deg': 3,
    'phoenix_morning_at_or_below_15deg': 0, 'no_effect_columns_used': True,
    'no_new_inclusion_cutoff': True, 'no_model_fit': True}, indent=2) + '\n')
print(json.dumps({'metadata_figure_created': str(out.relative_to(repo)), 'rows_verified': 16}))
