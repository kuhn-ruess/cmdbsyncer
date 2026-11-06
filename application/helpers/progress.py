"""
The progress bar of the exports
"""
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn


def make_progress():
    """Return the Syncer's standard rich Progress bar."""
    return Progress(SpinnerColumn(),
                    MofNCompleteColumn(),
                    *Progress.get_default_columns(),
                    TimeElapsedColumn())
