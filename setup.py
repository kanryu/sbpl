from setuptools import setup


requires = ["freetype-py>=2.0.0"]

with open('README.md') as f:
    readme = f.read()

with open('LICENSE') as f:
    license = f.read()

setup(
    name='sbpl',
    version='0.1.1.rev2',
    description='SBPL module for remote printing',
    long_description=readme,
    long_description_content_type='text/markdown',
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
