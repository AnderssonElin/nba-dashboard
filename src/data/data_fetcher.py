"""
Data fetching functions for NBA game analysis.
These functions retrieve data from the NBA API.
"""

import pandas as pd
from nba_api.stats.endpoints import leaguegamefinder, playbyplay
from datetime import datetime
import time


def get_recent_games(days=7, max_games=20):
    """
    Fetch recent NBA games from the NBA API.
    
    Args:
        days: Number of days to look back
        max_games: Maximum number of games to return
        
    Returns:
        DataFrame with recent games data
    """
    try:
        # Get games using the same approach as in the original code
        gamefinder = leaguegamefinder.LeagueGameFinder(league_id_nullable='00')
        games_df = gamefinder.get_data_frames()[0]
        
        # Sort games by date and game ID
        games_df = games_df.sort_values(by=['GAME_DATE', 'GAME_ID'], ascending=[False, False])
        games_df['GAME_DATE'] = pd.to_datetime(games_df['GAME_DATE'])
        
        # If no games found, create dummy data
        if games_df.empty:
            print("No analyzed results found, creating dummy data.")
            # Create dummy data with random game IDs
            import numpy as np
            games_df = pd.DataFrame({
                'GAME_ID': [f"002210{i}" for i in range(1, max_games + 1)],
                'GAME_DATE': [datetime.now().strftime('%Y-%m-%d')] * max_games,
                'MATCHUP': [f"Team {i} vs Team {i+1}" for i in range(1, max_games + 1)],
                'TEAM_ID': [1610612700 + i for i in range(1, max_games + 1)]
            })
        
        # Get recent games
        recent_games = games_df.head(max_games * 2)  # Get more games since each game appears twice
        
        return recent_games
    
    except Exception as e:
        print(f"Error fetching recent games: {e}")
        return pd.DataFrame()


def get_play_by_play_data(game_id):
    """
    Fetch play-by-play data for a specific game.
    
    Args:
        game_id: NBA game ID
        
    Returns:
        DataFrame with play-by-play data
    """
    try:
        # Get play-by-play data
        pbp = playbyplay.PlayByPlay(game_id=game_id)
        pbp_df = pbp.get_data_frames()[0]
        
        # Add delay to avoid rate limiting
        time.sleep(0.6)
        
        return pbp_df
    
    except Exception as e:
        print(f"Error fetching play-by-play data for game {game_id}: {e}")
        return pd.DataFrame()


def process_play_by_play_data(pbp_df):
    """
    Process play-by-play data to extract period scores.
    
    Args:
        pbp_df: DataFrame with play-by-play data
        
    Returns:
        DataFrame with period scores
    """
    if pbp_df.empty:
        return pd.DataFrame()
    
    try:
        # Replace 'TIE' with 0
        pbp_df['SCOREMARGIN'] = pbp_df['SCOREMARGIN'].replace('TIE', '0')
        
        # Convert score margin to numeric
        pbp_df['SCOREMARGIN'] = pd.to_numeric(pbp_df['SCOREMARGIN'], errors='coerce')
        
        # Extract home and away scores
        pbp_df[['SCORE_AWAY', 'SCORE_HOME']] = pbp_df['SCORE'].str.split(' - ', expand=True).apply(pd.to_numeric)
        
        # Group by period to get period scores
        period_scores = pbp_df.groupby('PERIOD').agg({
            'SCORE_HOME': 'last',
            'SCORE_AWAY': 'last'
        }).reset_index()
        
        # Calculate points per period
        period_scores['HOME_PTS_P1'] = period_scores.loc[period_scores['PERIOD'] == 1, 'SCORE_HOME'].values[0] if 1 in period_scores['PERIOD'].values else 0
        period_scores['AWAY_PTS_P1'] = period_scores.loc[period_scores['PERIOD'] == 1, 'SCORE_AWAY'].values[0] if 1 in period_scores['PERIOD'].values else 0
        
        for i in range(2, period_scores['PERIOD'].max() + 1):
            if i-1 in period_scores['PERIOD'].values and i in period_scores['PERIOD'].values:
                period_scores[f'HOME_PTS_P{i}'] = period_scores.loc[period_scores['PERIOD'] == i, 'SCORE_HOME'].values[0] - period_scores.loc[period_scores['PERIOD'] == i-1, 'SCORE_HOME'].values[0]
                period_scores[f'AWAY_PTS_P{i}'] = period_scores.loc[period_scores['PERIOD'] == i, 'SCORE_AWAY'].values[0] - period_scores.loc[period_scores['PERIOD'] == i-1, 'SCORE_AWAY'].values[0]
        
        return period_scores
    
    except Exception as e:
        print(f"Error processing play-by-play data: {e}")
        return pd.DataFrame() 