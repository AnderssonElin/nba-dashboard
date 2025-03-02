"""
NBA Game Analysis Dashboard

This is the main file for the NBA Game Analysis Dashboard.
It creates a Dash application that displays various visualizations
of NBA game data, including scores, margins, and correlations.
"""

import pandas as pd
import dash
from dash import dcc, html, dash_table
from dash.dependencies import Input, Output
import time

# Import custom modules
from src.data.data_fetcher import get_recent_games
from src.utils.game_analyzer import analyze_game
from src.utils.config import COLORS, FONTS, METRICS
from src.visualization.visualizations import (
    create_total_score_chart, create_margin_scatter_plot,
    create_radar_chart, create_correlation_matrix
)


def create_dashboard():
    """
    Create the NBA Game Analysis Dashboard.
    
    Returns:
        Dash application
    """
    # Get recent games
    recent_games = get_recent_games()
    
    # Filter for away games (games with '@' in matchup) and use all games if none found
    filtered_recent_games = recent_games[recent_games['MATCHUP'].str.contains('@')]
    unique_recent_games = filtered_recent_games.drop_duplicates(subset=['GAME_ID'])
    
    if unique_recent_games.empty:
        print("No away matches found, using all recent games instead.")
        unique_recent_games = recent_games.drop_duplicates(subset=['GAME_ID'])
    
    # Analyze games
    results = []
    for _, game in unique_recent_games.iterrows():
        game_id = game['GAME_ID']
        matchup = game['MATCHUP']
        game_date = game['GAME_DATE'].strftime('%Y-%m-%d')
        
        # Analyze game
        game_results = analyze_game(game_id, game_date, matchup)
        results.append(game_results)
    
    # If no results were calculated, create a dummy row
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
    
    # Define numeric columns for formatting
    numeric_columns = [
        'Period Scores', 'Extra Periods', 'Lead Changes', 'Buzzer Beater',
        'FG3_PCT', 'Star Performance', 'Margin', 'Total Score', 'Average Margin'
    ]
    
    # Round numeric columns to 1 decimal place
    for col in numeric_columns:
        if col in results_df.columns:
            results_df[col] = results_df[col].round(1)
    
    # Create visualizations
    fig_total_score = create_total_score_chart(results_df)
    fig_margin = create_margin_scatter_plot(results_df)
    fig_radar = create_radar_chart(results_df)
    fig_corr = create_correlation_matrix(results_df)
    
    # Create Dash app
    app = dash.Dash(__name__)
    
    # Create dropdown options from the results dataframe
    dropdown_options = [{'label': f"{row['Teams']} ({row['Game Date']})", 'value': i} 
                       for i, row in results_df.iterrows()]
    # Add an "All Games" option
    dropdown_options.insert(0, {'label': 'All Games', 'value': 'all'})
    
    # Define app layout
    app.layout = html.Div(children=[
        # Dashboard title
        html.H1(children='NBA Game Analysis Dashboard', style={
            'color': COLORS['primary'], 
            'textAlign': 'center', 
            'marginBottom': '30px',
            'fontFamily': FONTS['main'],
            'fontSize': FONTS['size']['title']
        }),
        
        # Dashboard description
        html.P(children='An interactive dashboard with advanced analysis of NBA games.', 
               style={
                   'color': COLORS['text'], 
                   'textAlign': 'center', 
                   'marginBottom': '40px', 
                   'fontSize': FONTS['size']['large'],
                   'fontFamily': FONTS['main']
               }),
               
        # Game filter dropdown
        html.Div([
            html.Label('Select Game:', style={
                'color': COLORS['text'],
                'marginRight': '15px',
                'fontFamily': FONTS['main'],
                'fontSize': FONTS['size']['normal']
            }),
            dcc.Dropdown(
                id='game-filter-dropdown',
                options=dropdown_options,
                value='all',
                style={
                    'backgroundColor': COLORS['card'],
                    'color': COLORS['background'],
                    'border': f'1px solid {COLORS["primary"]}',
                    'borderRadius': '5px',
                    'width': '100%',
                    'fontFamily': FONTS['main']
                }
            )
        ], style={
            'backgroundColor': COLORS['card'], 
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
        ], style={'backgroundColor': COLORS['card'], 'padding': '20px', 'borderRadius': '10px', 'marginBottom': '30px'}),
        
        # Margin vs Total Score scatter plot
        html.Div([
            dcc.Graph(
                id='margin-scatter-graph',
                figure=fig_margin,
                style={'marginBottom': '30px'}
            )
        ], style={'backgroundColor': COLORS['card'], 'padding': '20px', 'borderRadius': '10px', 'marginBottom': '30px'}),
        
        # Score Components radar chart
        html.Div([
            dcc.Graph(
                id='metric-breakdown-graph',
                figure=fig_radar,
                style={'marginBottom': '30px'}
            )
        ], style={'backgroundColor': COLORS['card'], 'padding': '20px', 'borderRadius': '10px', 'marginBottom': '30px'}),
        
        # Correlation matrix
        html.Div([
            dcc.Graph(
                id='correlation-matrix-graph',
                figure=fig_corr,
                style={'marginBottom': '30px'}
            )
        ], style={'backgroundColor': COLORS['card'], 'padding': '20px', 'borderRadius': '10px', 'marginBottom': '30px'}),
        
        # Detailed data table
        html.Div([
            html.H2('Games - Detailed Overview', style={
                'color': COLORS['primary'], 
                'textAlign': 'center', 
                'marginBottom': '20px',
                'fontFamily': FONTS['main'],
                'fontSize': FONTS['size']['header']
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
                    'backgroundColor': COLORS['card'],
                    'color': COLORS['primary'],
                    'fontWeight': 'bold',
                    'border': f'1px solid {COLORS["grid"]}',
                    'fontFamily': FONTS['main']
                },
                style_cell={
                    'textAlign': 'center', 
                    'backgroundColor': COLORS['background'], 
                    'color': COLORS['text'],
                    'border': f'1px solid {COLORS["grid"]}',
                    'padding': '10px',
                    'fontFamily': FONTS['main'],
                    'fontSize': FONTS['size']['normal']
                },
                style_data_conditional=[
                    {
                        'if': {'row_index': 'odd'},
                        'backgroundColor': COLORS['card']
                    }
                ]
            )
        ], style={'backgroundColor': COLORS['card'], 'padding': '20px', 'borderRadius': '10px'})
    ], style={
        'backgroundColor': COLORS['background'], 
        'color': COLORS['text'], 
        'padding': '40px', 
        'fontFamily': FONTS['main']
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
        
        # Update visualizations
        updated_fig_total_score = create_total_score_chart(filtered_df)
        updated_fig_margin = create_margin_scatter_plot(filtered_df)
        updated_fig_radar = create_radar_chart(filtered_df)
        
        return updated_fig_total_score, updated_fig_margin, updated_fig_radar, filtered_df.to_dict('records')
    
    return app


if __name__ == '__main__':
    app = create_dashboard()
    app.run_server(debug=True) 