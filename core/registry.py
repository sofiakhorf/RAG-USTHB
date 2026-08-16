from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Type
from core.models import PipelineConfig, Chunk

from abc import ABC, abstractmethod




class BaseFamilyParser(ABC):
    def __init__(self, config: Optional[PipelineConfig] = None):
        self.config = config or PipelineConfig()

    @abstractmethod
    def parse(self, file_path: str, document_title: Optional[str] = None) -> List[Chunk]:
      pass
       

class ParserRegistry:
    _registry: Dict[str, Type[BaseFamilyParser]] = {}

    @classmethod
    def register(cls, family_id: str):
        def decorator(subclass: Type[BaseFamilyParser]):
            cls._registry[family_id] = subclass
            return subclass
        return decorator

    @classmethod
    def get_parser(cls, family_id: str, config: PipelineConfig) -> BaseFamilyParser:
        if family_id not in cls._registry:
            raise ValueError(f"Famille non reconnue : {family_id}")
        return cls._registry[family_id](config=config)
