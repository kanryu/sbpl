from setuptools import setup


requires = ["freetype-py>=2.0.0"]


setup(
    name='sbpl',
    version='0.1',
    description='SBPL module for remote printing',
    url='https://github.com/kanryu/sbpl',
    author='KATO Kanryu',
    author_email='k.kanryu@gmail.com',
    license='MIT',
    keywords='sbpl printing socket freetype',
    packages=[
        "sbpl",
    ],
    install_requires=requires,
    classifiers=[
        'Topic :: Printing',
    ],
)
