# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/EugenioSorbellini/tv-voice-bridge/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                 |    Stmts |     Miss |   Cover |   Missing |
|----------------------------------------------------- | -------: | -------: | ------: | --------: |
| custom\_components/tv\_voice\_bridge/\_\_init\_\_.py |       39 |        1 |     97% |        51 |
| custom\_components/tv\_voice\_bridge/client.py       |      225 |       11 |     95% |88-92, 172, 174, 225, 255, 260-261 |
| custom\_components/tv\_voice\_bridge/config\_flow.py |       59 |        2 |     97% |     73-74 |
| custom\_components/tv\_voice\_bridge/const.py        |       19 |        0 |    100% |           |
| custom\_components/tv\_voice\_bridge/diagnostics.py  |        8 |        0 |    100% |           |
| custom\_components/tv\_voice\_bridge/errors.py       |        4 |        0 |    100% |           |
| custom\_components/tv\_voice\_bridge/frontend.py     |       10 |        0 |    100% |           |
| custom\_components/tv\_voice\_bridge/manager.py      |      156 |        5 |     97% |69-70, 83, 131, 147 |
| custom\_components/tv\_voice\_bridge/session.py      |      155 |        7 |     95% |61, 72, 85, 91-92, 123, 134 |
| custom\_components/tv\_voice\_bridge/target.py       |       37 |        1 |     97% |        55 |
| custom\_components/tv\_voice\_bridge/voice\_pb2.py   |       41 |       29 |     29% |     33-61 |
| custom\_components/tv\_voice\_bridge/websocket.py    |       71 |        4 |     94% |81-82, 115-116 |
| **TOTAL**                                            |  **824** |   **60** | **93%** |           |


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://raw.githubusercontent.com/EugenioSorbellini/tv-voice-bridge/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/EugenioSorbellini/tv-voice-bridge/blob/python-coverage-comment-action-data/htmlcov/index.html)

This is the one to use if your repository is private or if you don't want to customize anything.

### [Shields.io](https://shields.io) Json Endpoint

[![Coverage badge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/EugenioSorbellini/tv-voice-bridge/python-coverage-comment-action-data/endpoint.json)](https://htmlpreview.github.io/?https://github.com/EugenioSorbellini/tv-voice-bridge/blob/python-coverage-comment-action-data/htmlcov/index.html)

Using this one will allow you to [customize](https://shields.io/endpoint) the look of your badge.
It won't work with private repositories. It won't be refreshed more than once per five minutes.

### [Shields.io](https://shields.io) Dynamic Badge

[![Coverage badge](https://img.shields.io/badge/dynamic/json?color=brightgreen&label=coverage&query=%24.message&url=https%3A%2F%2Fraw.githubusercontent.com%2FEugenioSorbellini%2Ftv-voice-bridge%2Fpython-coverage-comment-action-data%2Fendpoint.json)](https://htmlpreview.github.io/?https://github.com/EugenioSorbellini/tv-voice-bridge/blob/python-coverage-comment-action-data/htmlcov/index.html)

This one will always be the same color. It won't work for private repos. I'm not even sure why we included it.

## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.