import pandas as pd
from nba_api.stats.endpoints import leaguegamefinder, playbyplay, boxscoretraditionalv2
from datetime import datetime, timedelta
import time
import dash
from dash import dcc, html, dash_table
from dash.dependencies import Input, Output
import plotly.express as px
import os
import json

# -----------------------------
# Configuration and weights for game scoring
# -----------------------------

# Cache variables for data
last_data_fetch_time = None
cached_results_df = None
DATA_FETCH_INTERVAL = 300  # 5 minutes in seconds

# Force a refresh by removing existing cache files at startup
def clear_cache():
    try:
        if os.path.exists('data_cache.csv'):
            os.remove('data_cache.csv')
            print("Removed data_cache.csv")
        if os.path.exists('data_cache.json'):
            os.remove('data_cache.json')
            print("Removed data_cache.json")
    except Exception as e:
        print(f"Error clearing cache: {e}")

# Clear cache at startup to force a fresh data fetch
clear_cache()

# Function to check if we should fetch new data
def should_fetch_data():
    global last_data_fetch_time
    
    # If we've never fetched data or the cache file doesn't exist, we should fetch
    if last_data_fetch_time is None:
        # Check if we have a cache file with a timestamp
        if os.path.exists('data_cache.json'):
            try:
                with open('data_cache.json', 'r') as f:
                    cache_data = json.load(f)
                    cache_timestamp = cache_data.get('timestamp', '2000-01-01T00:00:00')
                    last_data_fetch_time = datetime.fromisoformat(cache_timestamp)
                    
                    # Validate that the timestamp is not in the future
                    if last_data_fetch_time > datetime.now():
                        print(f"Cache timestamp is in the future ({last_data_fetch_time}), forcing refresh")
                        return True
                        
                    print(f"Last data fetch time: {last_data_fetch_time}")
            except Exception as e:
                print(f"Error reading cache timestamp: {e}")
                # If there's an error reading the cache, fetch new data
                return True
        else:
            print("No cache file found, fetching new data")
            return True
    
    # Check if enough time has passed since the last fetch
    current_time = datetime.now()
    time_since_last_fetch = current_time - last_data_fetch_time
    
    should_fetch = time_since_last_fetch.total_seconds() >= DATA_FETCH_INTERVAL
    if should_fetch:
        print(f"Cache expired ({time_since_last_fetch.total_seconds()} seconds old), fetching new data")
    else:
        print(f"Using cache ({time_since_last_fetch.total_seconds()} seconds old)")
    
    return should_fetch

# Function to save data to cache
def save_data_to_cache(df):
    global last_data_fetch_time
    
    try:
        # Create directory if it doesn't exist
        cache_dir = os.path.dirname('data_cache.csv')
        if cache_dir and not os.path.exists(cache_dir):
            os.makedirs(cache_dir)
        
        last_data_fetch_time = datetime.now()
        
        # Save the dataframe to a CSV file
        df.to_csv('data_cache.csv', index=False)
        print(f"Saved data to cache at {last_data_fetch_time}")
        
        # Save the timestamp to a JSON file
        with open('data_cache.json', 'w') as f:
            json.dump({
                'timestamp': last_data_fetch_time.isoformat()
            }, f)
        
        return True
    except Exception as e:
        print(f"Error saving data to cache: {e}")
        return False

# Function to load data from cache
def load_data_from_cache():
    try:
        if os.path.exists('data_cache.csv'):
            df = pd.read_csv('data_cache.csv')
            print(f"Loaded {len(df)} rows from cache")
            return df
        else:
            print("Cache file not found")
            return None
    except Exception as e:
        print(f"Error loading data from cache: {e}")
        return None

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
    Calculate the score for a period based on score margin.
    
    Args:
        period_df: DataFrame containing play-by-play data for the period
        column_name: Column name to use for score calculation
        weight: Weight to apply to the score
        
    Returns:
        float: The calculated period score
    """
    try:
        # Filter relevant columns and convert to numeric
        period_df = period_df[['PERIOD', 'EVENTMSGTYPE', 'SCORE', 'SCOREMARGIN', 'PCTIMESTRING']]
        period_df['SCOREMARGIN'] = pd.to_numeric(period_df['SCOREMARGIN'], errors='coerce')
        
        # Calculate scores for each period
        period_scores = {}
        total_period_score = 0
        
        for period in range(1, period_df['PERIOD'].max() + 1):
            period_data = period_df[period_df['PERIOD'] == period]
            if not period_data.empty:
                # Calculate average score margin for the period
                margins = period_data['SCOREMARGIN'].dropna()
                if not margins.empty:
                    average_margin = margins.abs().mean()
                    
                    # Closer games (lower average_margin) get higher scores
                    # Use an inverse relationship with a cap
                    period_score = min(100, 100 / (average_margin + 1)) * weight_config['period_weights'].get(period, 0.25)
                    period_scores[period] = period_score
                    total_period_score += period_score
        
        return total_period_score
    except Exception as e:
        print(f"Error calculating period score: {e}")
        return 0

def calculate_lead_changes_score(df, weight):
    """
    Calculate score based on number of lead changes in the game.
    
    Args:
        df: DataFrame containing play-by-play data
        weight: Weight to apply to the score
        
    Returns:
        float: The calculated lead changes score
    """
    try:
        # Convert SCOREMARGIN to numeric, replacing 'TIE' with 0
        df = df.copy()
        df.loc[df['SCOREMARGIN'] == 'TIE', 'SCOREMARGIN'] = '0'
        df['SCOREMARGIN'] = pd.to_numeric(df['SCOREMARGIN'], errors='coerce')
        
        # Count lead changes
        lead_changes = 0
        prev_lead = None
        
        for _, row in df.iterrows():
            if pd.notna(row['SCOREMARGIN']):
                current_lead = 'HOME' if row['SCOREMARGIN'] > 0 else ('AWAY' if row['SCOREMARGIN'] < 0 else 'TIE')
                
                if prev_lead is not None and prev_lead != current_lead and current_lead != 'TIE' and prev_lead != 'TIE':
                    lead_changes += 1
                
                prev_lead = current_lead
        
        # Calculate score based on lead changes
        if lead_changes >= 15:
            lead_changes_score = weight * 100
        elif lead_changes <= 5:
            lead_changes_score = 0
        else:
            lead_changes_score = weight * 100 * (lead_changes - 5) / 10
            
        return lead_changes_score
    except Exception as e:
        print(f"Error calculating lead changes score: {e}")
        return 0

def calculate_buzzer_beater_score(df, weight):
    """
    Calculate score based on buzzer beaters in the game.
    
    Args:
        df: DataFrame containing play-by-play data
        weight: Weight to apply to the score
        
    Returns:
        float: The calculated buzzer beater score
    """
    try:
        buzzer_beater_score = 0
        
        # Filter for scoring events (EVENTMSGTYPE 1 or 2) in the last 24 seconds of each period
        for period in range(1, df['PERIOD'].max() + 1):
            period_df = df[df['PERIOD'] == period].copy()
            
            if period_df.empty:
                continue
                
            # Convert PCTIMESTRING to seconds
            period_df['SECONDS'] = period_df['PCTIMESTRING'].apply(convert_pctimestring_to_seconds)
            
            # Filter for scoring events in the last 24 seconds
            last_seconds_df = period_df[(period_df['SECONDS'] <= 24) & 
                                       (period_df['EVENTMSGTYPE'].isin([1, 2]))]
            
            if not last_seconds_df.empty:
                # Award points based on how close to the buzzer
                for _, row in last_seconds_df.iterrows():
                    seconds = row['SECONDS']
                    if seconds <= 5:
                        # Last 5 seconds gets full weight
                        buzzer_beater_score += weight * 100
                    elif seconds <= 10:
                        # 6-10 seconds gets 75% weight
                        buzzer_beater_score += weight * 75
                    elif seconds <= 24:
                        # 11-24 seconds gets 50% weight
                        buzzer_beater_score += weight * 50
        
        # Cap the score at 100 * weight
        buzzer_beater_score = min(buzzer_beater_score, weight * 100)
            
        return buzzer_beater_score
    except Exception as e:
        print(f"Error calculating buzzer beater score: {e}")
        return 0

def get_fg_fg3_pct_score(recent_games, game_id, weight):
    """
    Calculate score based on field goal percentages.
    
    Args:
        recent_games: DataFrame containing recent games data
        game_id: ID of the current game
        weight: Weight to apply to the score
        
    Returns:
        float: The calculated field goal percentage score
    """
    try:
        # Get box score data for the game
        box_score = boxscoretraditionalv2.BoxScoreTraditionalV2(game_id=game_id).get_data_frames()[0]
        
        if box_score.empty:
            return 0
            
        # Calculate team field goal percentages
        team_stats = box_score.groupby('TEAM_ID').agg({
            'FGM': 'sum',
            'FGA': 'sum',
            'FG3M': 'sum',
            'FG3A': 'sum'
        }).reset_index()
        
        # Calculate percentages
        team_stats['FG_PCT'] = team_stats['FGM'] / team_stats['FGA']
        team_stats['FG3_PCT'] = team_stats['FG3M'] / team_stats['FG3A']
        
        # Replace NaN with 0
        team_stats.fillna(0, inplace=True)
        
        # Get maximum percentages
        max_fg_pct = team_stats['FG_PCT'].max()
        max_fg3_pct = team_stats['FG3_PCT'].max()
        
        # Calculate score based on percentages
        # Higher FG percentages result in higher scores
        fg_score = min(100, max_fg_pct * 200) * 0.3  # 30% weight to FG%
        fg3_score = min(100, max_fg3_pct * 250) * 0.7  # 70% weight to 3PT%
        
        combined_score = (fg_score + fg3_score) * weight
        
        return combined_score
    except Exception as e:
        print(f"Error calculating FG/FG3 score: {e}")
        return 0

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
    Calculate scores for margin and star performance.
    
    Args:
        pbp_df: DataFrame containing play-by-play data
        game_id: ID of the current game
        weight_margin: Weight to apply to the margin score
        weight_star: Weight to apply to the star performance score
        
    Returns:
        tuple: (margin_score, star_performance_score, average_margin)
    """
    try:
        # Calculate average margin
        pbp_df = pbp_df.copy()
        pbp_df.loc[pbp_df['SCOREMARGIN'] == 'TIE', 'SCOREMARGIN'] = '0'
        pbp_df['SCOREMARGIN'] = pd.to_numeric(pbp_df['SCOREMARGIN'], errors='coerce')
        
        # Filter out rows with NaN SCOREMARGIN
        filtered_df = pbp_df.dropna(subset=['SCOREMARGIN'])
        
        if filtered_df.empty:
            return 0, 0, 0
            
        # Calculate average margin
        average_margin = filtered_df['SCOREMARGIN'].abs().mean()
        
        # Calculate margin score - closer games get higher scores
        if average_margin <= 5:
            margin_score = weight_margin * 100
        elif average_margin >= 15:
            margin_score = 0
        else:
            margin_score = weight_margin * 100 * (15 - average_margin) / 10
            
        # Get box score data for star performance calculation
        box_score = boxscoretraditionalv2.BoxScoreTraditionalV2(game_id=game_id).get_data_frames()[0]
        
        if box_score.empty:
            return margin_score, 0, average_margin
            
        # Find max points scored by a player
        max_points = box_score['PTS'].max() if 'PTS' in box_score.columns else 0
        
        # Calculate star performance score
        if max_points >= 40:
            star_performance_score = weight_star * 100
        elif max_points <= 25:
            star_performance_score = 0
        else:
            star_performance_score = weight_star * 100 * (max_points - 25) / 15
            
        return margin_score, star_performance_score, average_margin
    except Exception as e:
        print(f"Error calculating margin and star performance: {e}")
        return 0, 0, 0

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
    Fetch recent NBA games from the API.
    
    Returns:
        DataFrame: A DataFrame containing recent NBA games, or None if an error occurs.
    """
    try:
        print("Fetching games from NBA API...")
        
        # Add a delay to avoid API rate limits
        time.sleep(1)
        
        # Get recent games - try with a more recent date range first
        try:
            # Try to get games from the last 30 days
            thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
            gamefinder = leaguegamefinder.LeagueGameFinder(
                date_from_nullable=thirty_days_ago,
                league_id_nullable='00'
            )
            games = gamefinder.get_data_frames()[0]
            
            if games.empty or len(games) < 5:  # If we get too few games, try a wider date range
                print(f"Found only {len(games) if not games.empty else 0} games in the last 30 days, trying a wider date range")
                raise Exception("Too few games found")
                
        except Exception as e:
            print(f"Error with initial date range: {e}, trying wider date range")
            # If that fails, try with a wider date range
            time.sleep(2)  # Add a delay before the second API call
            gamefinder = leaguegamefinder.LeagueGameFinder(
                date_from_nullable='2023-10-01',
                league_id_nullable='00'
            )
            games = gamefinder.get_data_frames()[0]
        
        if games.empty:
            print("No games found in API response")
            return None
            
        print(f"Found {len(games)} games in API response")
        
        # Sort games by date (most recent first)
        games['GAME_DATE'] = pd.to_datetime(games['GAME_DATE'])
        games = games.sort_values('GAME_DATE', ascending=False)
        
        # Limit to the 20 most recent games to avoid processing too many
        recent_games = games.head(20)
        print(f"Limited to {len(recent_games)} most recent games")
        
        # Try to filter for away games (games with '@' in matchup) and use all games if none found
        filtered_recent_games = recent_games[recent_games['MATCHUP'].str.contains('@')]
        unique_recent_games = filtered_recent_games.drop_duplicates(subset=['GAME_ID'])
        
        if unique_recent_games.empty:
            print("No away matches found, using all recent games instead.")
            unique_recent_games = recent_games.drop_duplicates(subset=['GAME_ID'])
        
        print(f"Final dataset contains {len(unique_recent_games)} unique games")
        
        # Format the date column
        unique_recent_games['GAME_DATE'] = pd.to_datetime(unique_recent_games['GAME_DATE']).dt.strftime('%Y-%m-%d')
        
        return unique_recent_games
    except Exception as e:
        print(f"Error fetching recent games: {e}")
        # Print more detailed error information
        import traceback
        traceback.print_exc()
        return None

# -----------------------------
# Main data processing
# -----------------------------
def process_data():
    global cached_results_df
    
    try:
        # Check if we should fetch new data or use cached data
        if should_fetch_data():
            print("Fetching fresh data...")
            recent_games = get_recent_games()
            
            # Process the data
            if recent_games is None or len(recent_games) == 0:
                print("No analyzed results found, creating dummy data.")
                # Create dummy data for testing
                results_df = create_dummy_data()
            else:
                # Process each game
                results = []
                successful_games = 0
                
                # Limit to processing at most 10 games to avoid timeouts
                games_to_process = min(10, len(recent_games))
                print(f"Will process up to {games_to_process} games")
                
                for i, game in recent_games.head(games_to_process).iterrows():
                    try:
                        game_id = game['GAME_ID']
                        game_date = game['GAME_DATE']
                        matchup = game['MATCHUP']
                        
                        print(f"Processing game {i+1}/{games_to_process}: {matchup} on {game_date}")
                        
                        # Get play-by-play data with retry logic
                        pbp_df = None
                        max_retries = 3
                        for retry in range(max_retries):
                            try:
                                # Add a delay to avoid API rate limits
                                time.sleep(1)
                                pbp_df = playbyplay.PlayByPlay(game_id=game_id).get_data_frames()[0]
                                break
                            except Exception as e:
                                print(f"Error fetching play-by-play data for game {game_id} (attempt {retry+1}/{max_retries}): {e}")
                                if retry == max_retries - 1:
                                    raise
                                time.sleep(2)  # Wait before retrying
                        
                        if pbp_df is None or pbp_df.empty:
                            print(f"No play-by-play data available for game {game_id}")
                            continue
                        
                        # Calculate scores for different metrics
                        period_score = calculate_period_score(pbp_df, 'SCORE', weight_config['period_score_weight'])
                        lead_changes_score = calculate_lead_changes_score(pbp_df, weight_config['lead_changes_weight'])
                        buzzer_beater_score = calculate_buzzer_beater_score(pbp_df, weight_config['buzzer_beater_weight'])
                        
                        # Get FG3 percentage score with retry logic
                        fg3_pct_score = 0
                        for retry in range(max_retries):
                            try:
                                # Add a delay to avoid API rate limits
                                time.sleep(1)
                                fg3_pct_score = get_fg_fg3_pct_score(recent_games, game_id, weight_config['fg3_pct_weight'])
                                break
                            except Exception as e:
                                print(f"Error calculating FG3 score for game {game_id} (attempt {retry+1}/{max_retries}): {e}")
                                if retry == max_retries - 1:
                                    # Use a default value if all retries fail
                                    fg3_pct_score = 0
                                time.sleep(2)  # Wait before retrying
                        
                        # Calculate margin and star performance scores with retry logic
                        margin_score, star_performance_score, avg_margin = 0, 0, 0
                        for retry in range(max_retries):
                            try:
                                # Add a delay to avoid API rate limits
                                time.sleep(1)
                                margin_score, star_performance_score, avg_margin = calculate_margin_and_star_performance_score(
                                    pbp_df, game_id, weight_config['margin_weight'], weight_config['star_performance_weight']
                                )
                                break
                            except Exception as e:
                                print(f"Error calculating margin/star performance for game {game_id} (attempt {retry+1}/{max_retries}): {e}")
                                if retry == max_retries - 1:
                                    # Use default values if all retries fail
                                    margin_score, star_performance_score, avg_margin = 0, 0, 0
                                time.sleep(2)  # Wait before retrying
                        
                        # Calculate extra periods score
                        max_period = pbp_df['PERIOD'].max()
                        extra_periods_score = (max_period - 4) * weight_config['extra_periods_weight'] if max_period > 4 else 0
                        
                        # Calculate total score
                        total_score = (
                            period_score + 
                            lead_changes_score + 
                            buzzer_beater_score + 
                            fg3_pct_score + 
                            margin_score + 
                            star_performance_score + 
                            extra_periods_score
                        )
                        
                        # Get grade based on total score
                        grade = get_grade(total_score)
                        
                        # Add to results
                        results.append({
                            'Game Date': game_date,
                            'Teams': matchup,
                            'Total Score': round(total_score, 1),
                            'Period Scores': round(period_score, 1),
                            'Extra Periods': round(extra_periods_score, 1),
                            'Lead Changes': round(lead_changes_score, 1),
                            'Buzzer Beater': round(buzzer_beater_score, 1),
                            'FG3_PCT': round(fg3_pct_score, 1),
                            'Star Performance': round(star_performance_score, 1),
                            'Margin': round(margin_score, 1),
                            'Average Margin': round(avg_margin, 1),
                            'Grade': grade
                        })
                        
                        successful_games += 1
                        print(f"Successfully processed game {matchup} with total score {round(total_score, 1)}")
                        
                    except Exception as e:
                        print(f"Error processing game {game_id if 'game_id' in locals() else 'unknown'}: {e}")
                        import traceback
                        traceback.print_exc()
                        continue
                
                # Create DataFrame from results
                if not results:
                    print("No games were successfully processed, creating dummy data.")
                    results_df = create_dummy_data()
                else:
                    results_df = pd.DataFrame(results)
                    
                    # Sort by total score (descending)
                    results_df = results_df.sort_values('Total Score', ascending=False).reset_index(drop=True)
                    print(f"Successfully processed {successful_games} out of {games_to_process} games.")
            
            # Save the processed data to cache
            if save_data_to_cache(results_df):
                cached_results_df = results_df
                print("Data successfully saved to cache.")
            else:
                print("Warning: Failed to save data to cache")
        else:
            print("Using cached data...")
            # Use cached data
            results_df = load_data_from_cache()
            if results_df is None or len(results_df) <= 3:
                # If loading fails or only contains dummy data, force a refresh
                print("Cached data is empty or contains only dummy data, forcing refresh.")
                # Clear cache and try again
                clear_cache()
                return process_data()
            cached_results_df = results_df
        
        return results_df
    except Exception as e:
        print(f"Unexpected error in process_data: {e}")
        import traceback
        traceback.print_exc()
        # Return dummy data as a fallback
        return create_dummy_data()

# Function to create dummy data
def create_dummy_data():
    print("Creating dummy data for testing.")
    return pd.DataFrame({
        'Game Date': ['2023-01-01', '2023-01-02', '2023-01-03'],
        'Teams': ['No Data', 'No Data', 'No Data'],
        'Total Score': [0, 0, 0],
        'Period Scores': [0, 0, 0],
        'Extra Periods': [0, 0, 0],
        'Lead Changes': [0, 0, 0],
        'Buzzer Beater': [0, 0, 0],
        'FG3_PCT': [0, 0, 0],
        'Star Performance': [0, 0, 0],
        'Margin': [0, 0, 0],
        'Average Margin': [0, 0, 0],
        'Grade': ['N/A', 'N/A', 'N/A']
    })

# Process the data
results_df = process_data()

# Define numeric columns for formatting
numeric_columns = ['Total Score', 'Period Scores', 'Extra Periods', 'Lead Changes', 
                  'Buzzer Beater', 'FG3_PCT', 'Star Performance', 'Margin', 'Average Margin']

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
# Reversed order for bar chart stacking (so A+ appears at the top)
grade_order_reversed = grade_order[::-1]

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
    category_orders={'Grade': grade_order_reversed},
    # Stack bars so A+ appears at the top
    barmode='stack'
)

# Set the legend order to match the original grade order (A+ at top)
fig_total_score.update_layout(
    legend=dict(
        traceorder='reversed',
        itemsizing='constant'
    )
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
    category_orders={'Grade': grade_order}  # Use original order for scatter plot
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
        category_orders={'Grade': grade_order_reversed},
        # Stack bars so A+ appears at the top
        barmode='stack'
    )
    
    # Set the legend order to match the original grade order (A+ at top)
    updated_fig_total_score.update_layout(
        legend=dict(
            traceorder='reversed',
            itemsizing='constant'
        )
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
        category_orders={'Grade': grade_order}  # Use original order for scatter plot
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
