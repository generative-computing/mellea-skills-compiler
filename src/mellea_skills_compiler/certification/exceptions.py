class CertificationInterrupted(KeyboardInterrupt):
    def __init__(self, signal_number: int) -> None:
        self.signal_number = signal_number
