# healthy - a tiny Linux process monitor

Inspired by [Vitals](https://hmarr.com/blog/vitals/), I present to you
`healthy`, which attempts to do the same, only for Linux.

![screenshot of healthy running](./screenshot.png)

## Installation

On Arch Linux, this can be installed as `healthy-git` from the
[AUR](https://wiki.archlinux.org/index.php/Arch_User_Repository):
https://aur.archlinux.org/packages/healthy-git.

## Development

To run this locally, clone the repository and run `python healthy.py`.

If there are missing dependencies, try the `./scripts/run` script.  This
script will install dependencies to a local `virtualenv` and then run
the application.

## License

`healthy` is licensed under GPLv3, see [`LICENSE`](./LICENSE) for
details.
