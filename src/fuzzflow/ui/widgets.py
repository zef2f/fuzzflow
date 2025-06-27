"""Custom widgets for the dashboard"""

from textual.reactive import reactive
from textual.widgets import Static


class ResourceGauge(Static):
    """Gauge widget for resource usage"""

    value = reactive(0.0)
    max_value = reactive(100.0)
    label = reactive("")

    def __init__(
        self,
        label: str = "",
        value: float = 0.0,
        max_value: float = 100.0,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.label = label
        self.value = value
        self.max_value = max_value

    def render(self) -> str:
        """Render the gauge"""
        if self.max_value <= 0:
            percentage = 0
        else:
            percentage = min(100, int((self.value / self.max_value) * 100))

        # Create progress bar
        bar_width = 20
        filled = int(bar_width * percentage / 100)
        empty = bar_width - filled

        bar = "█" * filled + "░" * empty

        # Color based on percentage
        if percentage < 50:
            color = "green"
        elif percentage < 80:
            color = "yellow"
        else:
            color = "red"

        return f"{self.label}: [{color}]{bar}[/{color}] {percentage}%"

