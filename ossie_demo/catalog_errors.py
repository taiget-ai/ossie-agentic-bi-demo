class SemanticError(ValueError):
    """Invalid or unsupported semantic request or Ossie model."""


class PipelineError(Exception):
    """Public, credential-free failure at an application boundary."""

    def __init__(self, code, stage, message, status=502):
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.status = status
