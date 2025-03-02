"""
Game analysis functions for NBA game analysis.
These functions calculate scores and grades for NBA games.
"""

import pandas as pd
import numpy as np
from datetime import datetime
from src.utils.config import ADJUSTED_PERIOD_WEIGHTS, WEIGHT_CONFIG
from src.utils.scoring_functions import (
    calculate_period_score, calculate_lead_changes_score, 
    calculate_buzzer_beater_score, get_fg_fg3_pct_score,
    calculate_margin_and_star_performance_score, get_grade
)
from src.data.data_fetcher import get_play_by_play_data, process_play_by_play_data


def analyze_game(game_id, game_date, matchup):
    """
    Analyze a game and calculate its score.
    
    Args:
        game_id: NBA game ID
        game_date: Date of the game
        matchup: Teams playing in the game
        
    Returns:
        Dictionary with game analysis results
    """
    # Get play-by-play data
    pbp_df = get_play_by_play_data(game_id)
    
    # If no data, return empty result
    if pbp_df.empty:
        return {
            'Game ID': game_id,
            'Game Date': game_date,
            'Teams': matchup,
            'Period Scores': 0,
            'Extra Periods': 0,
            'Lead Changes': 0,
            'Buzzer Beater': 0,
            'FG3_PCT': 0,
            'Star Performance': 0,
            'Margin': 0,
            'Total Score': 0,
            'Grade': 'N/A',
            'Average Margin': 0
        }
    
    # Process play-by-play data to get period scores
    period_scores = process_play_by_play_data(pbp_df)
    
    # Calculate period scores
    period_score_total = 0
    for period, weight in ADJUSTED_PERIOD_WEIGHTS.items():
        period_df = pbp_df[pbp_df['PERIOD'] == period].copy() if not pbp_df.empty else pd.DataFrame()
        if not period_df.empty:
            average_periodscore, period_score = calculate_period_score(period_df, 'SCOREMARGIN', weight)
            period_score_total += period_score
    
    # Calculate extra periods score (overtime)
    num_periods = pbp_df['PERIOD'].max() if not pbp_df.empty else 0
    extra_periods_score = 0
    if num_periods > 4:  # If there are overtime periods
        extra_periods_score = WEIGHT_CONFIG['extra_period_weight'] * 100
    
    # Calculate lead changes score
    lead_changes, lead_changes_score = calculate_lead_changes_score(pbp_df, WEIGHT_CONFIG['lead_change_weight'])
    
    # Calculate buzzer beater score
    buzzer_beater, buzzer_beater_score = calculate_buzzer_beater_score(pbp_df, WEIGHT_CONFIG['buzzer_beater_weight'])
    
    # Get recent games for FG3_PCT calculation
    from src.data.data_fetcher import get_recent_games
    recent_games = get_recent_games()
    
    # Calculate 3-point field goal percentage score
    max_fg_pct, max_fg3_pct, fg3_pct_score = get_fg_fg3_pct_score(recent_games, game_id, WEIGHT_CONFIG['fg3_pct_weight'])
    
    # Calculate margin and star performance scores
    try:
        average_margin, margin_score, max_points, star_performance_score = calculate_margin_and_star_performance_score(
            pbp_df, game_id, WEIGHT_CONFIG['margin_weight'], WEIGHT_CONFIG['star_performance_weight']
        )
    except Exception as e:
        print(f"Error calculating margin/star performance for game_id {game_id}: {e}")
        average_margin, margin_score, max_points, star_performance_score = 0, 0, 0, 0
    
    # Calculate total score
    total_score = period_score_total + extra_periods_score + lead_changes_score + buzzer_beater_score + fg3_pct_score + margin_score + star_performance_score
    
    # Get grade
    grade = get_grade(total_score)
    
    # Return results
    return {
        'Game ID': game_id,
        'Game Date': game_date,
        'Teams': matchup,
        'Period Scores': round(period_score_total, 1),
        'Extra Periods': round(extra_periods_score, 1),
        'Lead Changes': round(lead_changes_score, 1),
        'Buzzer Beater': round(buzzer_beater_score, 1),
        'FG3_PCT': round(fg3_pct_score, 1),
        'Star Performance': round(star_performance_score, 1),
        'Margin': round(margin_score, 1),
        'Total Score': round(total_score, 1),
        'Grade': grade,
        'Average Margin': round(average_margin, 1)
    } 