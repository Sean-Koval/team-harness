import argparse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    parser.add_argument("--verbatim", action="store_true")
    args = parser.parse_args()
    name = args.name if args.verbatim else args.name.strip()
    print(f"Hello, {name}!")


if __name__ == "__main__":
    main()
