from typing import Optional
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED


class InMemoryZip:
    """Class for creating in-memory zip files."""
    def __init__(
        self,
        filename: Optional[str] = None,
        mode: str = 'a',
        compression: int = ZIP_DEFLATED,
        **kwargs
    ):
        # Create the in-memory file-like object
        self.file_bytes = BytesIO()
        self.filename = filename
        self.ziphandler = self.create_handler(
            self.file_bytes,
            mode=mode,
            compression=compression,
            allowZip64=False,
            **kwargs
        )

    def create_handler(
        self,
        handler,
        mode: str = 'a',
        compression: int = ZIP_DEFLATED,
        **kwargs
    ) -> ZipFile:
        zf = ZipFile(
            handler,
            mode=mode,
            compression=compression,
            **kwargs
        )
        return zf

    def append(self, filename_in_zip: str, file_contents: str):
        """Appends a file with name filename_in_zip and contents of
        file_contents to the in-memory zip."""
        if not self.ziphandler:
            self.file_bytes = BytesIO()
            self.ziphandler = self.create_handler(
                self.file_bytes
            )
        # Get a handle to the in-memory zip in append mode
        # Write the file to the in-memory zip
        self.ziphandler.writestr(filename_in_zip, file_contents)

        # Mark the files as having been created on Windows so that
        # Unix permissions are not inferred as 0000
        for zfile in self.ziphandler.filelist:
            zfile.create_system = 0

        return self

    def get_bytes(self):
        """Returns a BytesIO from Zip File."""
        self.file_bytes.seek(0)
        self.ziphandler.close()
        return self.file_bytes

    def read(self):
        """Returns a string with the contents of the in-memory zip."""
        self.file_bytes.seek(0)
        self.ziphandler.close()
        return self.file_bytes.read()
