from io import BufferedReader
import os
from typing import Union


class KHUxFile:
    def __init__(self, file_path: Union[str, BufferedReader], file_name: str = "") -> None:
        if not file_path:
            raise ValueError("Invalid file passed")

        if isinstance(file_path, str):
            if not os.path.isfile(file_path):
                raise ValueError("File does not exist")
            self.file_handle = open(file_path, "rb")
            self.file_name = file_name or os.path.basename(file_path)
            self.file_path = file_path
        elif isinstance(file_path, BufferedReader):
            self.file_handle = file_path
            self.file_name = file_name
            self.file_path = None
            if not self.file_name:
                raise ValueError(
                    "File name must be specified when using a file stream."
                )
        else:
            raise ValueError("Invalid file type")
    
    def close(self) -> None:
        if self.file_handle:
            self.file_handle.close()
