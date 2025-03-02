"""
Configuration settings for the NBA Game Analysis Dashboard.
Contains weights for scoring components, color schemes, and font settings.
"""

# -----------------------------
# Configuration and weights for game scoring
# -----------------------------
WEIGHT_CONFIG = {
    'period_weights': {1: 0.33, 2: 0.33, 3: 0.34, 4: 0},  # Weights for each period
    'extra_period_weight': 0.05,      # Weight for overtime periods
    'lead_change_weight': 0.05,       # Weight for lead changes
    'buzzer_beater_weight': 0.0,      # Weight for buzzer-beaters
    'fg3_pct_weight': 0.05,           # Weight for 3-point field goal percentage
    'star_performance_weight': 0.1,   # Weight for star player performances
    'margin_weight': 0.25,            # Weight for final score margin
    'max_total_score': 0.50           # Maximum score for periods (excluding others)
}

# Adjust period weights based on max_total_score
ADJUSTED_PERIOD_WEIGHTS = {k: v * WEIGHT_CONFIG['max_total_score'] for k, v in WEIGHT_CONFIG['period_weights'].items()}

# -----------------------------
# Define a modern color scheme
# -----------------------------
COLORS = {
    'background': '#121212',  # Darker black for background
    'card': '#1E1E1E',        # Slightly lighter black for cards/panels
    'text': '#FFFFFF',        # White text
    'primary': '#BB86FC',     # Purple as primary color
    'secondary': '#03DAC6',   # Teal as secondary color
    'accent': '#CF6679',      # Pink/red as accent color
    'grid': '#333333'         # Dark gray for grid lines
}

# Define colors for different grades
GRADE_COLORS = {
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
GRADE_ORDER = ['A+', 'A', 'B+', 'B', 'C+', 'C', 'D', 'N/A']
# Reversed order for bar chart stacking (so A+ appears at the top)
GRADE_ORDER_REVERSED = GRADE_ORDER[::-1]

# Define metrics for analysis
METRICS = ['Period Scores', 'Extra Periods', 'Lead Changes', 'Buzzer Beater', 'FG3_PCT', 'Star Performance', 'Margin']

# Define font styles
FONTS = {
    'main': '"Consolas", "Monaco", "Courier New", monospace',  # SQL-like monospace font
    'size': {
        'small': '12px',
        'normal': '14px',
        'large': '18px',
        'title': '24px',
        'header': '20px'
    }
} 