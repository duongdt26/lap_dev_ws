from setuptools import find_packages, setup
import os
from glob import glob

package_name = 'amr_stm32_bridge'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='duo',
    maintainer_email='duongdoan261003@gmail.com',
    description='STM32 UART conveyor bridge for AMR',
    license='MIT',
    extras_require={'test': ['pytest']},
    entry_points={
        'console_scripts': [
            'stm32_conveyor_bridge_node = amr_stm32_bridge.stm32_conveyor_bridge_node:main',
        ],
    },
)
