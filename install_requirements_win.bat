call "C:\Program Files\Microsoft Visual Studio 9.0\Common7\Tools\vsvars32.bat"

IF "%VS100COMNTOOLS%" NEQ "" (
	SET VS90COMNTOOLS=%VS100COMNTOOLS%
)

::numpy 1.8.1
easy_install "numpy-1.8.1-sse3.exe" || exit /b
::lxml 3.3.5
easy_install "https://pypi.python.org/packages/2.7/l/lxml/lxml-3.3.5.win32-py2.7.exe#md5=2c10ce9cab81e0155a019fb6c0c3e2e9" || exit /b
::scipy 0.13.3
easy_install "http://sourceforge.net/projects/scipy/files/scipy/0.13.3/scipy-0.13.3-win32-superpack-python2.7.exe/download" || exit /b
::pycrypto 2.6
easy_install "http://www.voidspace.org.uk/downloads/pycrypto26/pycrypto-2.6.win32-py2.7.exe" || exit /b
::scikit-learn 0.14.1
easy_install "https://pypi.python.org/packages/2.7/s/scikit-learn/scikit-learn-0.14.1.win32-py2.7.exe#md5=8ae2354a7d48107865719bdee5715649" || exit /b
::umemcache 1.6.3
easy_install "https://pypi.python.org/packages/2.7/u/umemcache/umemcache-1.6.3.win32-py2.7.exe#md5=6fa154ee836e95576aa42f06690f6ac6" || exit /b

pip install -r requirements_win.txt || exit /b

:: py2exe
pip install http://sourceforge.net/projects/py2exe/files/latest/download?source=files
