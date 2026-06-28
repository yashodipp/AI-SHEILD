from __future__ import annotations

from dataclasses import dataclass

try:
    import torch
    from torch import nn
except Exception:  # pragma: no cover - optional dependency at runtime
    torch = None
    nn = None


@dataclass
class ModelAvailability:
    torch_ready: bool


def model_availability() -> ModelAvailability:
    return ModelAvailability(torch_ready=torch is not None and nn is not None)


if nn is not None:  # pragma: no branch
    class SpectrogramCNN(nn.Module):
        def __init__(self, mel_bins: int = 64, frames: int = 188, output_dim: int = 1) -> None:
            super().__init__()
            self.encoder = nn.Sequential(
                nn.Conv2d(1, 16, kernel_size=3, padding=1),
                nn.ReLU(),
                nn.BatchNorm2d(16),
                nn.MaxPool2d(2),
                nn.Conv2d(16, 32, kernel_size=3, padding=1),
                nn.ReLU(),
                nn.BatchNorm2d(32),
                nn.MaxPool2d(2),
                nn.Conv2d(32, 64, kernel_size=3, padding=1),
                nn.ReLU(),
                nn.AdaptiveAvgPool2d((8, 8)),
            )
            self.head = nn.Sequential(
                nn.Flatten(),
                nn.Linear(64 * 8 * 8, 128),
                nn.ReLU(),
                nn.Dropout(0.2),
                nn.Linear(128, output_dim),
            )

        def forward(self, x):
            return self.head(self.encoder(x))


    class TemporalLSTM(nn.Module):
        def __init__(self, input_dim: int = 32, hidden_dim: int = 96, output_dim: int = 1) -> None:
            super().__init__()
            self.recurrent = nn.LSTM(
                input_size=input_dim,
                hidden_size=hidden_dim,
                num_layers=2,
                batch_first=True,
                dropout=0.2,
                bidirectional=True,
            )
            self.head = nn.Sequential(
                nn.Linear(hidden_dim * 2, 96),
                nn.ReLU(),
                nn.Dropout(0.2),
                nn.Linear(96, output_dim),
            )

        def forward(self, x):
            output, _ = self.recurrent(x)
            pooled = output.mean(dim=1)
            return self.head(pooled)


    class AudioTransformerEncoder(nn.Module):
        def __init__(self, input_dim: int = 32, output_dim: int = 1, heads: int = 4) -> None:
            super().__init__()
            encoder_layer = nn.TransformerEncoderLayer(
                d_model=input_dim,
                nhead=heads,
                dim_feedforward=128,
                dropout=0.1,
                batch_first=True,
            )
            self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=2)
            self.head = nn.Sequential(
                nn.LayerNorm(input_dim),
                nn.Linear(input_dim, 64),
                nn.ReLU(),
                nn.Linear(64, output_dim),
            )

        def forward(self, x):
            encoded = self.encoder(x)
            pooled = encoded.mean(dim=1)
            return self.head(pooled)


    class VoiceEnsemble(nn.Module):
        def __init__(self, temporal_dim: int = 32) -> None:
            super().__init__()
            self.cnn = SpectrogramCNN()
            self.lstm = TemporalLSTM(input_dim=temporal_dim)
            self.transformer = AudioTransformerEncoder(input_dim=temporal_dim)
            self.mix = nn.Parameter(torch.tensor([0.34, 0.33, 0.33], dtype=torch.float32))

        def forward(self, mel, temporal):
            logits = torch.stack(
                [
                    self.cnn(mel).squeeze(-1),
                    self.lstm(temporal).squeeze(-1),
                    self.transformer(temporal).squeeze(-1),
                ],
                dim=-1,
            )
            weights = torch.softmax(self.mix, dim=0)
            return (logits * weights).sum(dim=-1, keepdim=True)
