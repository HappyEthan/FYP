import argparse


def main():
    parser=argparse.ArgumentParser(description='Linux XZ 电机与磁数据工作台；启动不自动使能或运动')
    parser.add_argument('--demo',action='store_true',help='连接模拟设备，不连接实物；仍需手动设零和使能')
    args=parser.parse_args()
    from .ui import main as run
    return run(demo=args.demo)


if __name__=='__main__': raise SystemExit(main())
