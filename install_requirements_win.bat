call "C:\Program Files\Microsoft Visual Studio 9.0\Common7\Tools\vsvars32.bat"

IF "%VS100COMNTOOLS%" NEQ "" (
	SET VS90COMNTOOLS=%VS100COMNTOOLS%
)

::pycrypto 2.6
easy_install "http://www.voidspace.org.uk/downloads/pycrypto26/pycrypto-2.6.win32-py2.7.exe" || exit /b
::umemcache 1.6.3
easy_install "https://pypi.python.org/packages/2.7/u/umemcache/umemcache-1.6.3.win32-py2.7.exe#md5=6fa154ee836e95576aa42f06690f6ac6" || exit /b

pip install -r requirements.txt || exit /b

:: py2exe
pip install http://sourceforge.net/projects/py2exe/files/latest/download?source=files
