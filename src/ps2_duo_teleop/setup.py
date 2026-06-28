from setuptools import find_packages, setup

package_name = 'ps2_duo_teleop'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/config', ['config/ps2_teleop.yaml']),
        ('share/' + package_name + '/launch', ['launch/ps2_teleop.launch.py']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='duo',
    maintainer_email='duongdoan261003@gmail.com',
    description='TODO: Package description',
    license='TODO: License declaration',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'ps2_teleop_node = ps2_duo_teleop.ps2_teleop_node:main',
        ],
    },
)
