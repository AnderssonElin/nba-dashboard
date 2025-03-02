import pandas as pd
from nba_api.stats.endpoints import leaguegamefinder, playbyplay, boxscoretraditionalv2
from datetime import datetime
import time
import dash
from dash import dcc, html, dash_table
import plotly.express as px

# -----------------------------
# Konfiguration och vikter
weight_config = {
    'period_weights': {1: 0.33, 2: 0.33, 3: 0.34, 4: 0}, 
    'extra_period_weight': 0.05,      # Vikt för extra perioder (övertid)
    'lead_change_weight': 0.05,       # Vikt för ledningsbyten
    'buzzer_beater_weight': 0.0,      # Vikt för buzzer-beater
    'fg3_pct_weight': 0.05,           # Vikt för FG3_PCT
    'star_performance_weight': 0.1,   # Vikt för stjärnprestationer
    'margin_weight': 0.25,            # Vikt för margin (slutresultat)
    'max_total_score': 0.50           # Maximal poäng för perioder (exkl. övriga)
}
adjusted_period_weights = {k: v * weight_config['max_total_score'] for k, v in weight_config['period_weights'].items()}

# -----------------------------
# Funktioner för beräkningar
def calculate_period_score(period_df, column_name, weight):
    # Ersätt 'TIE' med 0
    period_df.loc[period_df[column_name] == 'TIE', column_name] = 0
    period_df[column_name] = period_df[column_name].fillna(0).astype(float)
    period_df['PERIODSCORE'] = period_df[column_name].abs()
    filtered_df = period_df.dropna(subset=['SCORE'])
    average_periodscore = filtered_df['PERIODSCORE'].mean()
    
    if average_periodscore <= 7:
        period_score = weight * 100
    elif average_periodscore > 20:
        period_score = 0
    else:
        period_score = weight * 100 * (20 - average_periodscore) / 13
    return average_periodscore, period_score

def calculate_lead_changes_score(df, weight):
    lead_changes = 0
    previous_margin = None
    for margin in df['SCOREMARGIN']:
        if margin == 'TIE' or pd.isna(margin):
            continue
        try:
            margin = float(margin)
        except ValueError:
            continue
        if previous_margin is not None and ((previous_margin < 0 and margin > 0) or (previous_margin > 0 and margin < 0)):
            lead_changes += 1
        previous_margin = margin
    if lead_changes >= 12:
        lead_changes_score = weight * 100
    elif lead_changes <= 5:
        lead_changes_score = 0
    else:
        lead_changes_score = weight * 100 * (lead_changes - 5) / 7
    return lead_changes, lead_changes_score

def calculate_buzzer_beater_score(df, weight):
    last_margin = df['SCOREMARGIN'].iloc[-1]
    if last_margin == 'TIE' or pd.isna(last_margin):
        return 0, 0
    try:
        last_margin = float(last_margin)
    except ValueError:
        return 0, 0
    recent_values = []
    for margin in df['SCOREMARGIN'].iloc[::-1]:
        if margin == 'TIE' or pd.isna(margin):
            continue
        try:
            margin = float(margin)
            recent_values.append(margin)
        except ValueError:
            continue
        if len(recent_values) == 5:
            break
    if len(recent_values) < 2:
        return 0, 0
    for margin in recent_values:
        if (last_margin < 0 and margin > 0) or (last_margin > 0 and margin < 0):
            return 1, weight * 100
    return 0, 0

def get_fg_fg3_pct_score(recent_games, game_id, weight):
    fg_pct_scores = []
    fg3_pct_scores = []
    for _, row in recent_games[recent_games['GAME_ID']==game_id].iterrows():
        fg_pct = row['FG_PCT']
        fg3_pct = row['FG3_PCT']
        if fg_pct >= 0.5:
            fg_pct_score = weight * 100
        elif fg_pct <= 0.4:
            fg_pct_score = 0
        else:
            fg_pct_score = weight * 100 * (fg_pct - 0.4) / 0.1
        if fg3_pct >= 0.35:
            fg3_pct_score = weight * 100
        elif fg3_pct <= 0.25:
            fg3_pct_score = 0
        else:
            fg3_pct_score = weight * 100 * (fg3_pct - 0.25) / 0.1
        fg_pct_scores.append(fg_pct_score)
        fg3_pct_scores.append(fg3_pct_score)
    combined_score = max(max(fg_pct_scores), max(fg3_pct_scores))
    return max(fg_pct_scores), max(fg3_pct_scores), combined_score

def convert_pctimestring_to_seconds(pctimestring):
    minutes, seconds = map(int, pctimestring.split(':'))
    return minutes * 60 + seconds

def calculate_margin_and_star_performance_score(pbp_df, game_id, weight_margin, weight_star):
    boxscore = boxscoretraditionalv2.BoxScoreTraditionalV2(game_id=game_id)
    boxscore_df = boxscore.get_data_frames()[0]
    pbp_df['PCTIMESECONDS'] = pbp_df['PCTIMESTRING'].apply(convert_pctimestring_to_seconds)
    max_period = pbp_df['PERIOD'].max()
    filtered_pbp_df = pbp_df[(pbp_df['PERIOD'] == max_period) & (pbp_df['PCTIMESECONDS'] >= 300)]
    average_margin = filtered_pbp_df['SCOREMARGIN'].mean()
    if average_margin >= 15:
        margin_score = 0
    elif average_margin <= 5:
        margin_score = weight_margin * 100
    else:
        margin_score = weight_margin * 100 * (15 - average_margin) / 10
    max_points = boxscore_df['PTS'].max()
    if max_points >= 35:
        star_performance_score = weight_star * 100
    elif max_points <= 20:
        star_performance_score = 0
    else:
        star_performance_score = weight_star * 100 * (max_points - 20) / 15
    return average_margin, margin_score, max_points, star_performance_score

def get_grade(total_score):
    if total_score >= 93:
        return 'A+'
    elif total_score >= 85:
        return 'A'
    elif total_score >= 80:
        return 'B+'
    elif total_score >= 75:
        return 'B'
    elif total_score >= 70:
        return 'C+'
    elif total_score >= 65:
        return 'C'
    else:
        return 'D'

def get_recent_games():
    gamefinder = leaguegamefinder.LeagueGameFinder(league_id_nullable='00')
    games = gamefinder.get_data_frames()[0]
    games = games.sort_values(by=['GAME_DATE', 'GAME_ID'], ascending=[False, False])
    games['GAME_DATE'] = pd.to_datetime(games['GAME_DATE'])
    recent_games = games.head(10)  # Hämta de senaste 10 matcherna
    return recent_games

# -----------------------------
# Hämta matcher och säkerställ att vi får data
recent_games = get_recent_games()

# Försök filtrera på borta-matcher (matcher med '@' i matchup) och använd alla matcher om ingen hittas
filtered_recent_games = recent_games[recent_games['MATCHUP'].str.contains('@')]
unique_recent_games = filtered_recent_games.drop_duplicates(subset=['GAME_ID'])
if unique_recent_games.empty:
    print("Inga borta-matcher hittades, använder istället alla senaste matcher.")
    unique_recent_games = recent_games.drop_duplicates(subset=['GAME_ID'])

results = []

# Loopa genom matcherna och beräkna poäng
for _, game in unique_recent_games.iterrows():
    game_id = game['GAME_ID']
    matchup = game['MATCHUP']
    game_date = game['GAME_DATE'].strftime('%Y-%m-%d')
    try:
        pbp = playbyplay.PlayByPlay(game_id=game_id)
        pbp_df = pbp.get_data_frames()[0]
    except Exception as e:
        print(f"Fel vid hämtning av play-by-play för game_id {game_id}: {e}")
        continue

    pbp_df = pbp_df[['PERIOD', 'EVENTMSGTYPE', 'EVENTMSGACTIONTYPE', 'EVENTNUM', 'SCORE', 'SCOREMARGIN', 'PCTIMESTRING']]
    pbp_df['SCOREMARGIN'] = pd.to_numeric(pbp_df['SCOREMARGIN'], errors='coerce')

    total_scores = {column: 0 for column in ['Period Scores', 'Extra Periods', 'Lead Changes', 'Buzzer Beater', 'FG3_PCT', 'Star Performance', 'Margin']}
    period_scores = {period: 0 for period in adjusted_period_weights}

    for period, weight in adjusted_period_weights.items():
        period_df = pbp_df[pbp_df['PERIOD'] == period].copy()
        if not period_df.empty:
            average_periodscore, period_score = calculate_period_score(period_df, 'SCOREMARGIN', weight)
            period_scores[period] = period_score
    period_scores_total = sum(period_scores.values())
    total_scores['Period Scores'] = period_scores_total

    extra_periods = pbp_df[pbp_df['PERIOD'] > 4]
    if not extra_periods.empty:
        extra_score = weight_config['extra_period_weight'] * 100
        total_scores['Extra Periods'] = extra_score

    lead_changes, lead_changes_score = calculate_lead_changes_score(pbp_df, weight_config['lead_change_weight'])
    total_scores['Lead Changes'] = lead_changes_score

    buzzer_beater, buzzer_beater_score = calculate_buzzer_beater_score(pbp_df, weight_config['buzzer_beater_weight'])
    total_scores['Buzzer Beater'] = buzzer_beater_score

    max_fg_pct, max_fg3_pct, fg_combined_score = get_fg_fg3_pct_score(recent_games, game_id, weight_config['fg3_pct_weight'])
    total_scores['FG3_PCT'] = fg_combined_score

    try:
        average_margin, margin_score, max_points, star_performance_score = calculate_margin_and_star_performance_score(pbp_df, game_id, weight_config['margin_weight'], weight_config['star_performance_weight'])
    except Exception as e:
        print(f"Fel vid beräkning av margin/stjärnprestation för game_id {game_id}: {e}")
        average_margin, margin_score, max_points, star_performance_score = 0, 0, 0, 0

    total_scores['Margin'] = margin_score
    total_scores['Star Performance'] = star_performance_score

    total_score = round(sum(total_scores.values()), 1)
    grade = get_grade(total_score)

    results.append({
        'Game Date': game_date,
        'Teams': matchup,
        'Total Score': total_score,
        'Grade': grade,
        'Period Scores': period_scores_total,
        'Extra Periods': total_scores['Extra Periods'],
        'Lead Changes': total_scores['Lead Changes'],
        'Buzzer Beater': total_scores['Buzzer Beater'],
        'FG3_PCT': total_scores['FG3_PCT'],
        'Star Performance': total_scores['Star Performance'],
        'Margin': total_scores['Margin'],
        'Average Margin': average_margin
    })

# Om inga resultat beräknats, skapa en dummy-rad så att DataFrame inte blir tom
if not results:
    print("Inga analyserade resultat hittades, skapar dummy-data.")
    results = [{
       'Game Date': None,
       'Teams': 'Ingen Data',
       'Total Score': 0,
       'Grade': 'N/A',
       'Period Scores': 0,
       'Extra Periods': 0,
       'Lead Changes': 0,
       'Buzzer Beater': 0,
       'FG3_PCT': 0,
       'Star Performance': 0,
       'Margin': 0,
       'Average Margin': 0
    }]

results_df = pd.DataFrame(results)
print(results_df)

# -----------------------------
# Skapa visualiseringar för dashboarden
fig_total_score = px.bar(
    results_df,
    x='Game Date',
    y='Total Score',
    color='Grade',
    title='Total Score per Match',
    labels={'Game Date': 'Matchdatum', 'Total Score': 'Total Poäng'}
)

fig_margin = px.scatter(
    results_df,
    x='Average Margin',
    y='Total Score',
    color='Grade',
    title='Samband mellan Genomsnittlig Marginal och Total Poäng',
    labels={'Average Margin': 'Genomsnittlig Marginal', 'Total Score': 'Total Poäng'}
)

metrics = ['Period Scores', 'Extra Periods', 'Lead Changes', 'Buzzer Beater', 'FG3_PCT', 'Star Performance', 'Margin']
df_long = results_df.melt(id_vars=['Game Date'], value_vars=metrics, var_name='Metrik', value_name='Poäng')
fig_metric_breakdown = px.bar(
    df_long,
    x='Game Date',
    y='Poäng',
    color='Metrik',
    title='Uppdelning av Poängkomponenter per Match',
    labels={'Game Date': 'Matchdatum', 'Poäng': 'Poäng'}
)

corr_columns = ['Total Score'] + metrics + ['Average Margin']
correlation_matrix = results_df[corr_columns].corr()
fig_corr = px.imshow(
    correlation_matrix,
    text_auto=True,
    title='Korrelationsmatris',
    labels={'color': 'Korrelationskoefficient'}
)

# -----------------------------
# Skapa dashboarden med Dash
app = dash.Dash(__name__)

app.layout = html.Div(children=[
    html.H1(children='NBA Data Dashboard'),
    html.P(children='En interaktiv dashboard med avancerade analyser av NBA-matcher.'),

    dcc.Graph(
        id='total-score-graph',
        figure=fig_total_score
    ),
    dcc.Graph(
        id='margin-scatter-graph',
        figure=fig_margin
    ),
    dcc.Graph(
        id='metric-breakdown-graph',
        figure=fig_metric_breakdown
    ),
    dcc.Graph(
        id='correlation-matrix-graph',
        figure=fig_corr
    ),
    html.H2('Matcher - Detaljerad Översikt'),
    dash_table.DataTable(
        id='results-table',
        columns=[{'name': col, 'id': col} for col in results_df.columns],
        data=results_df.to_dict('records'),
        page_size=10,
        style_table={'overflowX': 'auto'},
        style_cell={'textAlign': 'center'},
    )
])

if __name__ == '__main__':
    app.run_server(debug=True)
