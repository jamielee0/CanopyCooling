from pathlib import Path
import csv
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
R=Path('/Users/jmlee/Documents/TreeProject'); E=R/'docs/v2/v6_2/execution/advisor_step1_20261026'
rows=list(csv.DictReader((R/'deliverables/Advisor_Step1_Inputs_23Passes_v6_2_20261026/pass_inputs_23.csv').open()))
values=[[r['city'].title(),r['orbit'],r['local_date'],f"{float(r['apparent_solar_hour']):.2f}",f"{float(r['solar_elevation_deg']):.2f}",f"{float(r['shortwave_W_m2']):.1f}",r['geolocation_categories'], 'Inputs only' if r['sample_role'].startswith('other') else '2023 pilot'] for r in rows]
fig,ax=plt.subplots(figsize=(12.5,10));ax.axis('off')
fig.suptitle('Step 1 input-table QA · 23 passes',fontsize=17,y=.97,fontweight='bold')
ax.set_title('Nonthermal inputs only · no new cooling fits',fontsize=11,pad=18)
t=ax.table(cellText=values,colLabels=['City','Orbit','Local date','Solar hour','Sun elev. °','SW W/m²','Scene QA','Scope'],loc='center',colWidths=[.12,.075,.15,.11,.11,.10,.13,.14])
t.auto_set_font_size(False);t.set_fontsize(10);t.scale(1,1.6)
for (r,c),cell in t.get_celld().items():
 cell.set_edgecolor('#d4dce3')
 if r==0:cell.set_facecolor('#17384f');cell.set_text_props(color='white',weight='bold')
 else:cell.set_facecolor('#eef4f8' if r%2==0 else 'white')
fig.text(.05,.025,'City-reference sun geometry; frozen Census city-domain HRRR mean. Exact per-scene flags are in the CSV.',fontsize=9)
fig.tight_layout(rect=[0,.04,1,.94]);fig.savefig(E/'pass_table_qa.png',dpi=150);plt.close(fig)
print(E/'pass_table_qa.png')
