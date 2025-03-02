"""
Visualization functions for NBA game analysis dashboard.
These functions create various plots and charts for the dashboard.
"""

import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import numpy as np
from src.utils.config import COLORS, GRADE_COLORS, GRADE_ORDER, GRADE_ORDER_REVERSED, FONTS, METRICS


def create_total_score_chart(results_df):
    """
    Create a bar chart showing total score per game.
    
    Args:
        results_df: DataFrame with game results
        
    Returns:
        Plotly figure object
    """
    fig = px.bar(
        results_df,
        x='Game Date',
        y='Total Score',
        color='Grade',
        title='Total Score per Game',
        labels={'Game Date': 'Game Date', 'Total Score': 'Total Score'},
        color_discrete_map=GRADE_COLORS,
        category_orders={'Grade': GRADE_ORDER_REVERSED},
        # Stack bars so A+ appears at the top
        barmode='stack'
    )
    
    # Set the legend order to match the original grade order (A+ at the top)
    fig.update_layout(
        legend=dict(
            traceorder='reversed',  # Reverse the legend order
            itemsizing='constant'
        ),
        paper_bgcolor=COLORS['background'],
        plot_bgcolor=COLORS['background'],
        font_color=COLORS['text'],
        title_font_color=COLORS['text'],
        legend_font_color=COLORS['text'],
        font_family=FONTS['main'],
        title_font_family=FONTS['main'],
        xaxis=dict(gridcolor=COLORS['grid'], zerolinecolor=COLORS['grid']),
        yaxis=dict(gridcolor=COLORS['grid'], zerolinecolor=COLORS['grid'], tickformat='.1f')
    )
    
    return fig


def create_margin_scatter_plot(results_df):
    """
    Create a scatter plot showing relationship between average margin and total score.
    
    Args:
        results_df: DataFrame with game results
        
    Returns:
        Plotly figure object
    """
    fig = px.scatter(
        results_df,
        x='Average Margin',
        y='Total Score',
        color='Grade',
        title='Relationship Between Average Margin and Total Score',
        labels={'Average Margin': 'Average Margin', 'Total Score': 'Total Score'},
        color_discrete_map=GRADE_COLORS,
        category_orders={'Grade': GRADE_ORDER}  # Use original order for scatter plot
    )
    
    fig.update_layout(
        paper_bgcolor=COLORS['background'],
        plot_bgcolor=COLORS['background'],
        font_color=COLORS['text'],
        title_font_color=COLORS['text'],
        legend_font_color=COLORS['text'],
        font_family=FONTS['main'],
        title_font_family=FONTS['main'],
        xaxis=dict(gridcolor=COLORS['grid'], zerolinecolor=COLORS['grid'], tickformat='.1f'),
        yaxis=dict(gridcolor=COLORS['grid'], zerolinecolor=COLORS['grid'], tickformat='.1f')
    )
    
    return fig


def create_radar_chart(results_df):
    """
    Create a radar chart showing average score by component.
    
    Args:
        results_df: DataFrame with game results
        
    Returns:
        Plotly figure object
    """
    # Calculate average scores for each component
    avg_scores = results_df[METRICS].mean().reset_index()
    avg_scores.columns = ['Component', 'Average Score']
    
    # Create radar chart for average component scores
    fig = go.Figure()
    
    # Add a single trace for the average scores
    fig.add_trace(go.Scatterpolar(
        r=avg_scores['Average Score'],
        theta=METRICS,
        fill='toself',
        name='Average Score',
        line_color=COLORS['primary']
    ))
    
    # Update layout
    fig.update_layout(
        polar=dict(
            radialaxis=dict(
                visible=True,
                range=[0, max(avg_scores['Average Score']) * 1.1],  # Set range with some padding
                tickfont=dict(color=COLORS['text'], family=FONTS['main']),
                gridcolor=COLORS['grid']
            ),
            angularaxis=dict(
                tickfont=dict(color=COLORS['text'], family=FONTS['main']),
                gridcolor=COLORS['grid']
            ),
            bgcolor=COLORS['background']
        ),
        paper_bgcolor=COLORS['background'],
        plot_bgcolor=COLORS['background'],
        font_color=COLORS['text'],
        title_text='Average Score by Component',
        title_font_color=COLORS['text'],
        title_font_family=FONTS['main'],
        legend_font_color=COLORS['text'],
        legend_font_family=FONTS['main'],
        showlegend=True
    )
    
    return fig


def create_correlation_matrix(results_df):
    """
    Create a correlation matrix for all metrics.
    
    Args:
        results_df: DataFrame with game results
        
    Returns:
        Plotly figure object
    """
    corr_columns = ['Total Score'] + METRICS + ['Average Margin']
    correlation_matrix = results_df[corr_columns].corr()
    
    fig = px.imshow(
        correlation_matrix,
        text_auto=True,
        title='Correlation Matrix',
        labels={'color': 'Correlation Coefficient'}
    )
    
    fig.update_layout(
        paper_bgcolor=COLORS['background'],
        plot_bgcolor=COLORS['background'],
        font_color=COLORS['text'],
        title_font_color=COLORS['text'],
        font_family=FONTS['main'],
        title_font_family=FONTS['main'],
        coloraxis_colorbar=dict(tickfont=dict(color=COLORS['text'], family=FONTS['main']))
    )
    
    # Update color scale for correlation matrix and format text to 1 decimal place
    fig.update_traces(
        colorscale=[[0, '#1E1E1E'], [0.5, COLORS['secondary']], [1, COLORS['primary']]],
        texttemplate='%{z:.1f}'
    )
    
    return fig 