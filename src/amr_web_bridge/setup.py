from setuptools import find_packages, setup

package_name = 'amr_web_bridge'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
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
            'map_bridge_node = amr_web_bridge.map_bridge_node:main',
            'nav_pose_bridge_node = amr_web_bridge.nav_pose_bridge_node:main',
            'mission_client_node = amr_web_bridge.mission_client_node:main',
        ],
    },
)
