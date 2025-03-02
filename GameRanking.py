import pandas as pd
from nba_api.stats.endpoints import leaguegamefinder, playbyplay, boxscoretraditionalv2
from datetime import datetime
import time
import dash
from dash import dcc, html, dash_table
from dash.dependencies import Input, Output
import plotly.express as px

# -----------------------------
# Configuration and weights for game scoring
# -----------------------------
weight_config = {
    'period_weights': {1: 0.33, 2: 0.33, 3: 0.34, 4: 0}, 
    'extra_period_weight': 0.05,      # Weight for overtime periods
    'lead_change_weight': 0.05,       # Weight for lead changes
    'buzzer_beater_weight': 0.0,      # Weight for buzzer-beaters
    'fg3_pct_weight': 0.05,           # Weight for 3-point field goal percentage
    'star_performance_weight': 0.1,   # Weight for star player performances
    'margin_weight': 0.25,            # Weight for final score margin
    'max_total_score': 0.50           # Maximum score for periods (excluding others)
}
# Adjust period weights based on max_total_score
adjusted_period_weights = {k: v * weight_config['max_total_score'] for k, v in weight_config['period_weights'].items()}

# -----------------------------
# Functions for calculating game scores
# -----------------------------

def calculate_period_score(period_df, column_name, weight):
    """
    Calculate the score for a specific period based on score margin.
    
    Args:
        period_df: DataFrame containing play-by-play data for the period
        column_name: Column name for score margin
        weight: Weight for this period in the total score
        
    Returns:
        Tuple of (average_periodscore, period_score)
    """
    # Replace 'TIE' with 0
    period_df.loc[period_df[column_name] == 'TIE', column_name] = 0
    period_df[column_name] = period_df[column_name].fillna(0).astype(float)
    period_df['PERIODSCORE'] = period_df[column_name].abs()
    filtered_df = period_df.dropna(subset=['SCORE'])
    average_periodscore = filtered_df['PERIODSCORE'].mean()
    
    # Calculate period score - closer games (lower average_periodscore) get higher scores
    if average_periodscore <= 7:
        period_score = weight * 100
    elif average_periodscore > 20:
        period_score = 0
    else:
        period_score = weight * 100 * (20 - average_periodscore) / 13
    return average_periodscore, period_score

def calculate_lead_changes_score(df, weight):
    """
    Calculate score based on number of lead changes in the game.
    
    Args:
        df: DataFrame containing play-by-play data
        weight: Weight for lead changes in the total score
        
    Returns:
        Tuple of (lead_changes, lead_changes_score)
    """
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
    
    # More lead changes result in higher scores
    if lead_changes >= 12:
        lead_changes_score = weight * 100
    elif lead_changes <= 5:
        lead_changes_score = 0
    else:
        lead_changes_score = weight * 100 * (lead_changes - 5) / 7
    return lead_changes, lead_changes_score

def calculate_buzzer_beater_score(df, weight):
    """
    Calculate a score based on buzzer beaters (shots made in the last seconds of a period).
    
    Args:
        df: Play-by-play DataFrame
        weight: Weight for buzzer beater score
        
    Returns:
        tuple: (Boolean indicating if there was a buzzer beater, calculated score)
    """
    # Check if DataFrame is empty
    if df.empty:
        return False, 0
        
    # Initialize variables
    buzzer_beater = False
    buzzer_beater_score = 0
    
    # Check if we have SCOREMARGIN column
    if 'SCOREMARGIN' not in df.columns:
        return False, 0
    
    # Get the last margin
    try:
        last_margin = df['SCOREMARGIN'].iloc[-1]
        
        # Convert 'TIE' to 0
        if last_margin == 'TIE':
            last_margin = 0
        else:
            last_margin = int(last_margin)
        
        # Check for buzzer beaters in the last 24 seconds of any period
        for period in df['PERIOD'].unique():
            period_df = df[df['PERIOD'] == period]
            
            # Skip if period_df is empty
            if period_df.empty:
                continue
                
            last_plays = period_df[period_df['PCTIMESTRING'].apply(
                lambda x: convert_pctimestring_to_seconds(x) <= 24 if isinstance(x, str) else False
            )]
            
            # Skip if last_plays is empty
            if last_plays.empty:
                continue
                
            for _, play in last_plays.iterrows():
                if 'HOMEDESCRIPTION' in play and isinstance(play['HOMEDESCRIPTION'], str) and 'SHOT' in play['HOMEDESCRIPTION'] and play['HOMEDESCRIPTION'].endswith('MADE'):
                    buzzer_beater = True
                    break
                if 'AWAYDESCRIPTION' in play and isinstance(play['AWAYDESCRIPTION'], str) and 'SHOT' in play['AWAYDESCRIPTION'] and play['AWAYDESCRIPTION'].endswith('MADE'):
                    buzzer_beater = True
                    break
        
        # Calculate score based on buzzer beater and final margin
        if buzzer_beater:
            # Higher score for closer games
            if abs(last_margin) <= 3:
                buzzer_beater_score = weight
            elif abs(last_margin) <= 5:
                buzzer_beater_score = weight * 0.8
            else:
                buzzer_beater_score = weight * 0.5
    except Exception as e:
        print(f"Error calculating buzzer beater score: {e}")
        return False, 0
        
    return buzzer_beater, buzzer_beater_score

def get_fg_fg3_pct_score(recent_games, game_id, weight):
    """
    Calculate score based on field goal and 3-point field goal percentages.
    
    Args:
        recent_games: DataFrame containing recent games data
        game_id: ID of the current game
        weight: Weight for FG3_PCT in the total score
        
    Returns:
        Tuple of (max_fg_pct_score, max_fg3_pct_score, combined_score)
    """
    fg_pct_scores = []
    fg3_pct_scores = []
    for _, row in recent_games[recent_games['GAME_ID']==game_id].iterrows():
        fg_pct = row['FG_PCT']
        fg3_pct = row['FG3_PCT']
        
        # Higher FG percentages result in higher scores
        if fg_pct >= 0.5:
            fg_pct_score = weight * 100
        elif fg_pct <= 0.4:
            fg_pct_score = 0
        else:
            fg_pct_score = weight * 100 * (fg_pct - 0.4) / 0.1
            
        # Higher 3PT percentages result in higher scores
        if fg3_pct >= 0.35:
            fg3_pct_score = weight * 100
        elif fg3_pct <= 0.25:
            fg3_pct_score = 0
        else:
            fg3_pct_score = weight * 100 * (fg3_pct - 0.25) / 0.1
            
        fg_pct_scores.append(fg_pct_score)
        fg3_pct_scores.append(fg3_pct_score)
        
    # Take the maximum of FG and 3PT scores
    combined_score = max(max(fg_pct_scores), max(fg3_pct_scores))
    return max(fg_pct_scores), max(fg3_pct_scores), combined_score

def convert_pctimestring_to_seconds(pctimestring):
    """
    Convert period clock time string (MM:SS) to seconds.
    
    Args:
        pctimestring: Period clock time string in MM:SS format
        
    Returns:
        Total seconds
    """
    minutes, seconds = map(int, pctimestring.split(':'))
    return minutes * 60 + seconds

def calculate_margin_and_star_performance_score(pbp_df, game_id, weight_margin, weight_star):
    """
    Calculate scores based on game margin and star player performances.
    
    Args:
        pbp_df: DataFrame containing play-by-play data
        game_id: ID of the current game
        weight_margin: Weight for margin in the total score
        weight_star: Weight for star performance in the total score
        
    Returns:
        Tuple of (average_margin, margin_score, max_points, star_performance_score)
    """
    # Get box score data for the game
    boxscore = boxscoretraditionalv2.BoxScoreTraditionalV2(game_id=game_id)
    boxscore_df = boxscore.get_data_frames()[0]
    
    # Convert period clock time to seconds
    pbp_df['PCTIMESECONDS'] = pbp_df['PCTIMESTRING'].apply(convert_pctimestring_to_seconds)
    
    # Calculate average margin in the last 5 minutes of the game
    max_period = pbp_df['PERIOD'].max()
    filtered_pbp_df = pbp_df[(pbp_df['PERIOD'] == max_period) & (pbp_df['PCTIMESECONDS'] >= 300)]
    average_margin = filtered_pbp_df['SCOREMARGIN'].mean()
    
    # Closer games (lower average_margin) get higher scores
    if average_margin >= 15:
        margin_score = 0
    elif average_margin <= 5:
        margin_score = weight_margin * 100
    else:
        margin_score = weight_margin * 100 * (15 - average_margin) / 10
        
    # Higher max points by a player results in higher star performance score
    max_points = boxscore_df['PTS'].max()
    if max_points >= 35:
        star_performance_score = weight_star * 100
    elif max_points <= 20:
        star_performance_score = 0
    else:
        star_performance_score = weight_star * 100 * (max_points - 20) / 15
        
    return average_margin, margin_score, max_points, star_performance_score

def get_grade(total_score):
    """
    Convert numerical score to letter grade.
    
    Args:
        total_score: Numerical score
        
    Returns:
        Letter grade (A+, A, B+, B, C+, C, D)
    """
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
    """
    Fetch recent NBA games using the NBA API.
    
    Returns:
        DataFrame containing recent games data
    """
    gamefinder = leaguegamefinder.LeagueGameFinder(league_id_nullable='00')
    games = gamefinder.get_data_frames()[0]
    games = games.sort_values(by=['GAME_DATE', 'GAME_ID'], ascending=[False, False])
    games['GAME_DATE'] = pd.to_datetime(games['GAME_DATE'])
    recent_games = games.head(20)  # Get the 10 most recent games
    return recent_games

# -----------------------------
# Fetch games and ensure we have data
# -----------------------------
recent_games = get_recent_games()

# Try to filter for away games (games with '@' in matchup) and use all games if none found
filtered_recent_games = recent_games[recent_games['MATCHUP'].str.contains('@')]
unique_recent_games = filtered_recent_games.drop_duplicates(subset=['GAME_ID'])
if unique_recent_games.empty:
    print("No away matches found, using all recent games instead.")
    unique_recent_games = recent_games.drop_duplicates(subset=['GAME_ID'])

results = []

# -----------------------------
# Loop through games and calculate scores
# -----------------------------
for _, game in unique_recent_games.iterrows():
    game_id = game['GAME_ID']
    matchup = game['MATCHUP']
    game_date = game['GAME_DATE'].strftime('%Y-%m-%d')
    try:
        # Get play-by-play data for the game
        pbp = playbyplay.PlayByPlay(game_id=game_id)
        pbp_df = pbp.get_data_frames()[0]
    except Exception as e:
        print(f"Error fetching play-by-play for game_id {game_id}: {e}")
        continue

    # Filter relevant columns from play-by-play data
    pbp_df = pbp_df[['PERIOD', 'EVENTMSGTYPE', 'EVENTMSGACTIONTYPE', 'EVENTNUM', 'SCORE', 'SCOREMARGIN', 'PCTIMESTRING']]
    pbp_df['SCOREMARGIN'] = pd.to_numeric(pbp_df['SCOREMARGIN'], errors='coerce')

    # Initialize score components
    total_scores = {column: 0 for column in ['Period Scores', 'Extra Periods', 'Lead Changes', 'Buzzer Beater', 'FG3_PCT', 'Star Performance', 'Margin']}
    period_scores = {period: 0 for period in adjusted_period_weights}

    # Calculate scores for each period
    for period, weight in adjusted_period_weights.items():
        period_df = pbp_df[pbp_df['PERIOD'] == period].copy()
        if not period_df.empty:
            average_periodscore, period_score = calculate_period_score(period_df, 'SCOREMARGIN', weight)
            period_scores[period] = period_score
    period_scores_total = sum(period_scores.values())
    total_scores['Period Scores'] = period_scores_total

    # Check for overtime periods
    extra_periods = pbp_df[pbp_df['PERIOD'] > 4]
    if not extra_periods.empty:
        extra_score = weight_config['extra_period_weight'] * 100
        total_scores['Extra Periods'] = extra_score

    # Calculate lead changes score
    lead_changes, lead_changes_score = calculate_lead_changes_score(pbp_df, weight_config['lead_change_weight'])
    total_scores['Lead Changes'] = lead_changes_score

    # Calculate buzzer beater score
    buzzer_beater, buzzer_beater_score = calculate_buzzer_beater_score(pbp_df, weight_config['buzzer_beater_weight'])
    total_scores['Buzzer Beater'] = buzzer_beater_score

    # Calculate field goal percentage score
    max_fg_pct, max_fg3_pct, fg_combined_score = get_fg_fg3_pct_score(recent_games, game_id, weight_config['fg3_pct_weight'])
    total_scores['FG3_PCT'] = fg_combined_score

    # Calculate margin and star performance scores
    try:
        average_margin, margin_score, max_points, star_performance_score = calculate_margin_and_star_performance_score(pbp_df, game_id, weight_config['margin_weight'], weight_config['star_performance_weight'])
    except Exception as e:
        print(f"Error calculating margin/star performance for game_id {game_id}: {e}")
        average_margin, margin_score, max_points, star_performance_score = 0, 0, 0, 0

    total_scores['Margin'] = margin_score
    total_scores['Star Performance'] = star_performance_score

    # Calculate total score and grade
    total_score = round(sum(total_scores.values()), 1)
    grade = get_grade(total_score)

    # Add game results to results list
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

# If no results were calculated, create a dummy row so DataFrame isn't empty
if not results:
    print("No analyzed results found, creating dummy data.")
    results = [{
       'Game Date': None,
       'Teams': 'No Data',
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

# Create DataFrame from results
results_df = pd.DataFrame(results)
print(results_df)

# Round numeric columns to 1 decimal place
numeric_columns = ['Total Score', 'Period Scores', 'Extra Periods', 'Lead Changes', 
                  'Buzzer Beater', 'FG3_PCT', 'Star Performance', 'Margin', 'Average Margin']
for col in numeric_columns:
    if col in results_df.columns:
        results_df[col] = results_df[col].round(1)

# -----------------------------
# Define a modern color scheme
# -----------------------------
colors = {
    'background': '#121212',  # Darker black for background
    'card': '#1E1E1E',        # Slightly lighter black for cards/panels
    'text': '#FFFFFF',        # White text
    'primary': '#BB86FC',     # Purple as primary color
    'secondary': '#03DAC6',   # Teal as secondary color
    'accent': '#CF6679',      # Pink/red as accent color
    'grid': '#333333'         # Dark gray for grid lines
}

# Define colors for different grades
grade_colors = {
    'A+': '#BB86FC',  # Primary color (purple)
    'A': '#9D65F9',   # Lighter purple
    'B+': '#03DAC6',  # Secondary color (teal)
    'B': '#00B5A3',   # Darker teal
    'C+': '#CF6679',  # Accent color (pink/red)
    'C': '#B04759',   # Darker pink/red
    'D': '#FF7597',   # Lighter pink
    'N/A': '#666666'  # Gray for N/A
}

# Define grade order for consistent display
grade_order = ['A+', 'A', 'B+', 'B', 'C+', 'C', 'D', 'N/A']

# Define font styles
fonts = {
    'main': '"Consolas", "Monaco", "Courier New", monospace',  # SQL-like monospace font
    'size': {
        'small': '12px',
        'normal': '14px',
        'large': '18px',
        'title': '24px',
        'header': '20px'
    }
}

# -----------------------------
# Create visualizations for the dashboard
# -----------------------------

# Bar chart for total score per game
fig_total_score = px.bar(
    results_df,
    x='Game Date',
    y='Total Score',
    color='Grade',
    title='Total Score per Game',
    labels={'Game Date': 'Game Date', 'Total Score': 'Total Score'},
    color_discrete_map=grade_colors,
    category_orders={'Grade': grade_order}
)

# Reverse the order of the bars so A+ appears at the top
fig_total_score.update_layout(
    legend_traceorder='reversed'
)

# Scatter plot for relationship between average margin and total score
fig_margin = px.scatter(
    results_df,
    x='Average Margin',
    y='Total Score',
    color='Grade',
    title='Relationship Between Average Margin and Total Score',
    labels={'Average Margin': 'Average Margin', 'Total Score': 'Total Score'},
    color_discrete_map=grade_colors,
    category_orders={'Grade': grade_order}
)

# Bar chart for breakdown of score components per game
metrics = ['Period Scores', 'Extra Periods', 'Lead Changes', 'Buzzer Beater', 'FG3_PCT', 'Star Performance', 'Margin']
df_long = results_df.melt(id_vars=['Game Date'], value_vars=metrics, var_name='Metric', value_name='Score')
fig_metric_breakdown = px.bar(
    df_long,
    x='Game Date',
    y='Score',
    color='Metric',
    title='Breakdown of Score Components per Game',
    labels={'Game Date': 'Game Date', 'Score': 'Score'},
    category_orders={'Metric': metrics}  # Ensure consistent order of metrics
)

# Use a color scheme that matches our design
fig_metric_breakdown.update_layout(colorway=[colors['primary'], colors['secondary'], colors['accent'], '#64DFDF', '#80FFDB', '#7400B8', '#6930C3'])

# Create a custom color palette for metrics
metric_colors = {
    'Period Scores': colors['primary'],
    'Extra Periods': colors['secondary'],
    'Lead Changes': colors['accent'],
    'Buzzer Beater': '#64DFDF',
    'FG3_PCT': '#80FFDB',
    'Star Performance': '#7400B8',
    'Margin': '#6930C3'
}

# Update colors for each metric in the graph
for metric in metrics:
    fig_metric_breakdown.for_each_trace(
        lambda trace: trace.update(marker_color=metric_colors[trace.name]) 
        if trace.name in metric_colors else None
    )

# Correlation matrix for all metrics
corr_columns = ['Total Score'] + metrics + ['Average Margin']
correlation_matrix = results_df[corr_columns].corr()
fig_corr = px.imshow(
    correlation_matrix,
    text_auto=True,
    title='Correlation Matrix',
    labels={'color': 'Correlation Coefficient'}
)

# -----------------------------
# Update graph layouts with color scheme and font
# -----------------------------

# Update total score graph layout
fig_total_score.update_layout(
    paper_bgcolor=colors['background'],
    plot_bgcolor=colors['background'],
    font_color=colors['text'],
    title_font_color=colors['text'],
    legend_font_color=colors['text'],
    font_family=fonts['main'],
    title_font_family=fonts['main'],
    xaxis=dict(gridcolor=colors['grid'], zerolinecolor=colors['grid']),
    yaxis=dict(gridcolor=colors['grid'], zerolinecolor=colors['grid'], tickformat='.1f')
)

# Update margin scatter plot layout
fig_margin.update_layout(
    paper_bgcolor=colors['background'],
    plot_bgcolor=colors['background'],
    font_color=colors['text'],
    title_font_color=colors['text'],
    legend_font_color=colors['text'],
    font_family=fonts['main'],
    title_font_family=fonts['main'],
    xaxis=dict(gridcolor=colors['grid'], zerolinecolor=colors['grid'], tickformat='.1f'),
    yaxis=dict(gridcolor=colors['grid'], zerolinecolor=colors['grid'], tickformat='.1f')
)

# Update metric breakdown graph layout
fig_metric_breakdown.update_layout(
    paper_bgcolor=colors['background'],
    plot_bgcolor=colors['background'],
    font_color=colors['text'],
    title_font_color=colors['text'],
    legend_font_color=colors['text'],
    font_family=fonts['main'],
    title_font_family=fonts['main'],
    xaxis=dict(gridcolor=colors['grid'], zerolinecolor=colors['grid']),
    yaxis=dict(gridcolor=colors['grid'], zerolinecolor=colors['grid'], tickformat='.1f')
)

# Update correlation matrix layout
fig_corr.update_layout(
    paper_bgcolor=colors['background'],
    plot_bgcolor=colors['background'],
    font_color=colors['text'],
    title_font_color=colors['text'],
    font_family=fonts['main'],
    title_font_family=fonts['main'],
    coloraxis_colorbar=dict(tickfont=dict(color=colors['text'], family=fonts['main']))
)

# Update color scale for correlation matrix and format text to 1 decimal place
fig_corr.update_traces(
    colorscale=[[0, '#1E1E1E'], [0.5, colors['secondary']], [1, colors['primary']]],
    texttemplate='%{z:.1f}'
)

# -----------------------------
# Create the dashboard with Dash
# -----------------------------
app = dash.Dash(__name__)

# Create dropdown options from the results dataframe
dropdown_options = [{'label': f"{row['Teams']} ({row['Game Date']})", 'value': i} 
                   for i, row in results_df.iterrows()]
# Add an "All Games" option
dropdown_options.insert(0, {'label': 'All Games', 'value': 'all'})

app.layout = html.Div(children=[
    # Dashboard title
    html.H1(children='NBA Game Analysis Dashboard', style={
        'color': colors['primary'], 
        'textAlign': 'center', 
        'marginBottom': '30px',
        'fontFamily': fonts['main'],
        'fontSize': fonts['size']['title']
    }),
    
    # Dashboard description
    html.P(children='An interactive dashboard with advanced analysis of NBA games.', 
           style={
               'color': colors['text'], 
               'textAlign': 'center', 
               'marginBottom': '40px', 
               'fontSize': fonts['size']['large'],
               'fontFamily': fonts['main']
           }),
           
    # Game filter dropdown
    html.Div([
        html.Label('Select Game:', style={
            'color': colors['text'],
            'marginRight': '15px',
            'fontFamily': fonts['main'],
            'fontSize': fonts['size']['normal']
        }),
        dcc.Dropdown(
            id='game-filter-dropdown',
            options=dropdown_options,
            value='all',
            style={
                'backgroundColor': colors['card'],
                'color': colors['background'],
                'border': f'1px solid {colors["primary"]}',
                'borderRadius': '5px',
                'width': '100%',
                'fontFamily': fonts['main']
            }
        )
    ], style={
        'backgroundColor': colors['card'], 
        'padding': '20px', 
        'borderRadius': '10px', 
        'marginBottom': '30px',
        'display': 'flex',
        'alignItems': 'center'
    }),

    # Total Score per Game chart
    html.Div([
        dcc.Graph(
            id='total-score-graph',
            figure=fig_total_score,
            style={'marginBottom': '30px'}
        )
    ], style={'backgroundColor': colors['card'], 'padding': '20px', 'borderRadius': '10px', 'marginBottom': '30px'}),
    
    # Margin vs Total Score scatter plot
    html.Div([
        dcc.Graph(
            id='margin-scatter-graph',
            figure=fig_margin,
            style={'marginBottom': '30px'}
        )
    ], style={'backgroundColor': colors['card'], 'padding': '20px', 'borderRadius': '10px', 'marginBottom': '30px'}),
    
    # Score Components breakdown chart
    html.Div([
        dcc.Graph(
            id='metric-breakdown-graph',
            figure=fig_metric_breakdown,
            style={'marginBottom': '30px'}
        )
    ], style={'backgroundColor': colors['card'], 'padding': '20px', 'borderRadius': '10px', 'marginBottom': '30px'}),
    
    # Correlation matrix
    html.Div([
        dcc.Graph(
            id='correlation-matrix-graph',
            figure=fig_corr,
            style={'marginBottom': '30px'}
        )
    ], style={'backgroundColor': colors['card'], 'padding': '20px', 'borderRadius': '10px', 'marginBottom': '30px'}),
    
    # Detailed data table
    html.Div([
        html.H2('Games - Detailed Overview', style={
            'color': colors['primary'], 
            'textAlign': 'center', 
            'marginBottom': '20px',
            'fontFamily': fonts['main'],
            'fontSize': fonts['size']['header']
        }),
        dash_table.DataTable(
            id='results-table',
            columns=[
                # Format numeric columns to 1 decimal place
                {'name': col, 'id': col, 'type': 'numeric', 'format': {'specifier': '.1f'}} 
                if col in numeric_columns else {'name': col, 'id': col} 
                for col in results_df.columns
            ],
            data=results_df.to_dict('records'),
            page_size=10,
            style_table={'overflowX': 'auto'},
            style_header={
                'backgroundColor': colors['card'],
                'color': colors['primary'],
                'fontWeight': 'bold',
                'border': f'1px solid {colors["grid"]}',
                'fontFamily': fonts['main']
            },
            style_cell={
                'textAlign': 'center', 
                'backgroundColor': colors['background'], 
                'color': colors['text'],
                'border': f'1px solid {colors["grid"]}',
                'padding': '10px',
                'fontFamily': fonts['main'],
                'fontSize': fonts['size']['normal']
            },
            style_data_conditional=[
                {
                    'if': {'row_index': 'odd'},
                    'backgroundColor': colors['card']
                }
            ]
        )
    ], style={'backgroundColor': colors['card'], 'padding': '20px', 'borderRadius': '10px'})
], style={
    'backgroundColor': colors['background'], 
    'color': colors['text'], 
    'padding': '40px', 
    'fontFamily': fonts['main']
})

# Define callback to update graphs based on dropdown selection
@app.callback(
    [Output('total-score-graph', 'figure'),
     Output('margin-scatter-graph', 'figure'),
     Output('metric-breakdown-graph', 'figure'),
     Output('results-table', 'data')],
    [Input('game-filter-dropdown', 'value')]
)
def update_graphs(selected_game):
    # Filter data based on selection
    if selected_game == 'all':
        filtered_df = results_df
    else:
        filtered_df = results_df.iloc[[int(selected_game)]]
    
    # Update Total Score graph
    updated_fig_total_score = px.bar(
        filtered_df,
        x='Game Date',
        y='Total Score',
        color='Grade',
        title='Total Score per Game',
        labels={'Game Date': 'Game Date', 'Total Score': 'Total Score'},
        color_discrete_map=grade_colors,
        category_orders={'Grade': grade_order}
    )
    
    # Reverse the order of the bars so A+ appears at the top
    updated_fig_total_score.update_layout(
        legend_traceorder='reversed'
    )
    
    # Update Margin vs Total Score scatter plot
    updated_fig_margin = px.scatter(
        filtered_df,
        x='Average Margin',
        y='Total Score',
        color='Grade',
        title='Relationship Between Average Margin and Total Score',
        labels={'Average Margin': 'Average Margin', 'Total Score': 'Total Score'},
        color_discrete_map=grade_colors,
        category_orders={'Grade': grade_order}
    )
    
    # Update Score Components breakdown chart
    df_long = filtered_df.melt(id_vars=['Game Date'], value_vars=metrics, var_name='Metric', value_name='Score')
    updated_fig_metric_breakdown = px.bar(
        df_long,
        x='Game Date',
        y='Score',
        color='Metric',
        title='Breakdown of Score Components per Game',
        labels={'Game Date': 'Game Date', 'Score': 'Score'},
        category_orders={'Metric': metrics}  # Ensure consistent order of metrics
    )
    
    # Apply the same styling to updated graphs
    for fig in [updated_fig_total_score, updated_fig_margin, updated_fig_metric_breakdown]:
        fig.update_layout(
            paper_bgcolor=colors['background'],
            plot_bgcolor=colors['background'],
            font_color=colors['text'],
            title_font_color=colors['text'],
            legend_font_color=colors['text'],
            font_family=fonts['main'],
            title_font_family=fonts['main'],
            xaxis=dict(gridcolor=colors['grid'], zerolinecolor=colors['grid']),
            yaxis=dict(gridcolor=colors['grid'], zerolinecolor=colors['grid'], tickformat='.1f')
        )
    
    # Update colors for metric breakdown
    updated_fig_metric_breakdown.update_layout(colorway=[colors['primary'], colors['secondary'], colors['accent'], '#64DFDF', '#80FFDB', '#7400B8', '#6930C3'])
    
    # Update colors for each metric in the graph
    for metric in metrics:
        updated_fig_metric_breakdown.for_each_trace(
            lambda trace: trace.update(marker_color=metric_colors[trace.name]) 
            if trace.name in metric_colors else None
        )
    
    return updated_fig_total_score, updated_fig_margin, updated_fig_metric_breakdown, filtered_df.to_dict('records')

# Run the server
if __name__ == '__main__':
    app.run_server(debug=True)
