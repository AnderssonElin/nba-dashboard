"""
Scoring functions for NBA game analysis.
These functions calculate scores for different aspects of NBA games.
"""

import pandas as pd
import numpy as np
from datetime import datetime


def calculate_period_score(period_df, column_name, weight):
    """
    Calculate score based on how close each period was.
    
    Args:
        period_df: DataFrame with period scores
        column_name: Column name for the period to analyze
        weight: Weight to apply to this period's score
        
    Returns:
        Tuple of (average_periodscore, period_score)
    """
    try:
        if period_df.empty:
            return 0, 0
            
        # Replace 'TIE' with 0
        period_df.loc[period_df[column_name] == 'TIE', column_name] = 0
        period_df[column_name] = period_df[column_name].fillna(0).astype(float)
        period_df['PERIODSCORE'] = period_df[column_name].abs()
        filtered_df = period_df.dropna(subset=['SCORE']) if 'SCORE' in period_df.columns else period_df
        average_periodscore = filtered_df['PERIODSCORE'].mean() if not filtered_df.empty else 0
        
        # Calculate period score - closer games (lower average_periodscore) get higher scores
        if average_periodscore <= 7:
            period_score = weight * 100
        elif average_periodscore > 20:
            period_score = 0
        else:
            period_score = weight * 100 * (20 - average_periodscore) / 13
            
        return average_periodscore, period_score
        
    except Exception as e:
        print(f"Error calculating period score: {e}")
        return 0, 0


def calculate_lead_changes_score(df, weight):
    """
    Calculate score based on number of lead changes in the game.
    
    Args:
        df: DataFrame with play-by-play data
        weight: Weight for lead changes in the total score
        
    Returns:
        Tuple of (lead_changes, lead_changes_score)
    """
    try:
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
        
    except Exception as e:
        print(f"Error calculating lead changes score: {e}")
        return 0, 0


def calculate_buzzer_beater_score(df, weight):
    """
    Calculate score based on presence of buzzer beaters.
    
    Args:
        df: DataFrame with play-by-play data
        weight: Weight for buzzer beater in the total score
        
    Returns:
        Tuple of (buzzer_beater, buzzer_beater_score)
    """
    buzzer_beater = False
    buzzer_beater_score = 0
    
    try:
        # Check for buzzer beaters in the last 24 seconds of any period
        for period in df['PERIOD'].unique():
            period_df = df[df['PERIOD'] == period].copy()
            if period_df.empty:
                continue
                
            # Convert period clock time to seconds
            period_df['PCTIMESECONDS'] = period_df['PCTIMESTRING'].apply(convert_pctimestring_to_seconds)
            
            # Get the last margin
            last_row = period_df.iloc[-1]
            last_margin = last_row['SCOREMARGIN']
            if isinstance(last_margin, str):
                if last_margin == 'TIE':
                    last_margin = 0
                else:
                    try:
                        last_margin = float(last_margin)
                    except:
                        last_margin = 0
            
            # Check for shots in the last 24 seconds that changed the outcome
            last_seconds_df = period_df[period_df['PCTIMESECONDS'] <= 24]
            if not last_seconds_df.empty:
                for _, row in last_seconds_df.iterrows():
                    if row['EVENTMSGTYPE'] in [1, 2, 3]:  # Field goal, free throw, 3-pointer
                        buzzer_beater = True
                        break
        
        # Calculate score based on buzzer beater and final margin
        if buzzer_beater:
            # Higher score for closer games
            if abs(last_margin) <= 3:
                buzzer_beater_score = weight * 100
            elif abs(last_margin) <= 5:
                buzzer_beater_score = weight * 100 * 0.8
            else:
                buzzer_beater_score = weight * 100 * 0.5
    
    except Exception as e:
        print(f"Error calculating buzzer beater score: {e}")
        return False, 0
        
    return buzzer_beater, buzzer_beater_score


def get_fg_fg3_pct_score(recent_games, game_id, weight):
    """
    Calculate score based on field goal and 3-point field goal percentages.
    
    Args:
        recent_games: DataFrame with recent games data
        game_id: ID of the game to analyze
        weight: Weight to apply to FG3 percentage score
        
    Returns:
        Tuple of (max_fg_pct_score, max_fg3_pct_score, combined_score)
    """
    if recent_games.empty or game_id not in recent_games['GAME_ID'].values:
        return 0, 0, 0
    
    try:
        fg_pct_scores = []
        fg3_pct_scores = []
        
        # Get rows for this game (one for each team)
        game_rows = recent_games[recent_games['GAME_ID'] == game_id]
        
        for _, row in game_rows.iterrows():
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
        max_fg_pct_score = max(fg_pct_scores) if fg_pct_scores else 0
        max_fg3_pct_score = max(fg3_pct_scores) if fg3_pct_scores else 0
        combined_score = max(max_fg_pct_score, max_fg3_pct_score)
        
        return max_fg_pct_score, max_fg3_pct_score, combined_score
    
    except Exception as e:
        print(f"Error calculating FG/FG3 percentage score: {e}")
        return 0, 0, 0


def convert_pctimestring_to_seconds(pctimestring):
    """
    Convert period clock time string to seconds.
    
    Args:
        pctimestring: Period clock time string (MM:SS format)
        
    Returns:
        Time in seconds
    """
    try:
        if pd.isna(pctimestring) or pctimestring == '':
            return 0
            
        parts = pctimestring.split(':')
        if len(parts) == 2:
            minutes = int(parts[0])
            seconds = float(parts[1])
            return minutes * 60 + seconds
        else:
            return 0
    except Exception as e:
        print(f"Error converting time string: {e}")
        return 0


def calculate_margin_and_star_performance_score(pbp_df, game_id, weight_margin, weight_star):
    """
    Calculate scores based on game margin and star player performances.
    
    Args:
        pbp_df: DataFrame with play-by-play data
        game_id: ID of the game to analyze
        weight_margin: Weight for margin score
        weight_star: Weight for star performance score
        
    Returns:
        Tuple of (average_margin, margin_score, max_points, star_performance_score)
    """
    try:
        # Get box score data for the game
        from nba_api.stats.endpoints import boxscoretraditionalv2
        boxscore = boxscoretraditionalv2.BoxScoreTraditionalV2(game_id=game_id)
        boxscore_df = boxscore.get_data_frames()[0]
        
        # Convert period clock time to seconds
        pbp_df['PCTIMESECONDS'] = pbp_df['PCTIMESTRING'].apply(convert_pctimestring_to_seconds)
        
        # Calculate average margin in the last 5 minutes of the game
        max_period = pbp_df['PERIOD'].max()
        filtered_pbp_df = pbp_df[(pbp_df['PERIOD'] == max_period) & (pbp_df['PCTIMESECONDS'] >= 300)]
        average_margin = filtered_pbp_df['SCOREMARGIN'].abs().mean() if not filtered_pbp_df.empty else 0
        
        # Closer games (lower average_margin) get higher scores
        if average_margin >= 15:
            margin_score = 0
        elif average_margin <= 5:
            margin_score = weight_margin * 100
        else:
            margin_score = weight_margin * 100 * (15 - average_margin) / 10
            
        # Higher max points by a player results in higher star performance score
        max_points = boxscore_df['PTS'].max() if 'PTS' in boxscore_df.columns else 0
        if max_points >= 35:
            star_performance_score = weight_star * 100
        elif max_points <= 20:
            star_performance_score = 0
        else:
            star_performance_score = weight_star * 100 * (max_points - 20) / 15
            
        return average_margin, margin_score, max_points, star_performance_score
    
    except Exception as e:
        print(f"Error calculating margin/star performance score: {e}")
        return 0, 0, 0, 0


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