from pyfedappwrap.engine.config.system_config import system_settings
from pyfedappwrap.engine.runtime import FedDBEngine

from app import FfqExtractorApp

print(system_settings)

engine = FedDBEngine()
engine.register(FfqExtractorApp())

if __name__ == "__main__":
    engine.start()
    engine.wait_until_stop()
