from glob import glob
from setuptools import find_packages, setup


package_name = 'amr_magnetic_line_follower'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml', 'README.md']),
        ('share/' + package_name + '/config', glob('config/*.yaml')),
    ],
    install_requires=['setuptools'],
    tests_require=['pytest'],
    zip_safe=True,
    maintainer='duo',
    maintainer_email='duongdoan261003@gmail.com',
    description='Magnetic-line approach controller for AMR loading stations.',
    license='Apache-2.0',
    entry_points={
        'console_scripts': [
            'magnetic_line_follower_node = '
            'amr_magnetic_line_follower.magnetic_line_follower_node:main',
        ],
    },
)
