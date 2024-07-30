import os
import time
import json
import requests
from dotenv import load_dotenv
import pandas as pd
from typing import List, Dict, Any, Tuple
from requests.models import Response

# Load environment variables from .env file
load_dotenv()

GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
ORGANIZATION = os.getenv('ORGANIZATION')
LANGUAGE = os.getenv('LANGUAGE')
MAX_ITEMS_PER_PAGE = 100

# Dependency files dictionary
dependency_files = {
    'requirements.txt': 'pip',
    'pyproject.toml': 'poetry or other build systems'
}


class GhsGithub:
    def __init__(self, token: str):
        self.token = token

    def check_API_rate_limit(self, response: Response) -> bool:
        if response.status_code == 403 and 'X-Ratelimit-Remaining' in response.headers:
            if int(response.headers['X-Ratelimit-Remaining']) == 0:
                print(f"\t403 forbidden response header shows X-Ratelimit-Remaining at {
                      response.headers['X-Ratelimit-Remaining']} requests.")
                self.sleep_until_ratelimit_reset_time(
                    int(response.headers['X-RateLimit-Reset']))
        return response.status_code == 403 and 'X-Ratelimit-Remaining' in response.headers

    def sleep_until_ratelimit_reset_time(self, reset_timestamp: int):
        sleep_time = max(reset_timestamp - int(time.time()), 0)
        print(f"Sleeping for {sleep_time} seconds due to rate limit.")
        time.sleep(sleep_time)

    def github_request_exponential_backoff(self, url: str, params: Dict[str, Any] = {}, single_page: bool = False) -> List[Dict]:
        exponential_backoff_retry_delays_list: List[int] = [
            1, 2, 4, 8, 16, 32, 64]
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "Authorization": f"Bearer {self.token}"
        }

        retry: bool = False
        response: Response = Response()
        retry_url: str = None
        pages_list: List[Dict] = []

        if "per_page" not in params:
            params["per_page"] = MAX_ITEMS_PER_PAGE

        while True:
            try:
                response = requests.get(url, headers=headers, params=params)
            except requests.exceptions.Timeout:
                print("Initial request timed out.")
                retry = True
            except requests.exceptions.RequestException as e:
                print(f"Request for {url} exception {e}")
                retry = True

            if retry or (response is not None and response.status_code != 200):
                if response.status_code == 422 and response.reason == "Unprocessable Entity":
                    dict_error: Dict[str, Any] = json.loads(response.text)
                    print(f"Skipping: {response.status_code} {response.reason} for url {url}\n\t{
                          dict_error['message']}\n\t{dict_error['errors'][0]['message']}")

                elif retry or response.status_code == 202 or response.status_code == 403:  # Try again
                    for retry_attempt_delay in exponential_backoff_retry_delays_list:
                        if 'Location' in response.headers:
                            retry_url = response.headers.get('Location')
                        # The only time we override the exponential backoff if we are asked by Github to wait
                        if 'Retry-After' in response.headers:
                            retry_attempt_delay = int(
                                response.headers.get('Retry-After'))
                        # Wait for n seconds before checking the status
                        time.sleep(retry_attempt_delay)
                        retry_response_url: str = retry_url if retry_url else url
                        print(f"Retrying request for {retry_response_url} after {
                              retry_attempt_delay} sec due to {response.status_code} response")
                        # A 403 may require us to take a nap
                        self.check_API_rate_limit(response)

                        try:
                            response = requests.get(
                                retry_response_url, headers=headers)
                        except requests.exceptions.Timeout:
                            print(f"Retry request timed out. retrying in {
                                  retry_attempt_delay} seconds.")
                            continue
                        # Check if the retry response is 200
                        if response.status_code == 200:
                            break  # Exit the loop on successful response
                        else:
                            print(f"\tRetried request and still got bad response status code: {
                                  response.status_code}")

            if response.status_code == 200:
                page_json = response.json()
                if not page_json or (isinstance(page_json, list) and not page_json):
                    break  # Exit if the page is empty
                pages_list.append(page_json)
            else:
                self.check_API_rate_limit(response)
                print(f"Retries exhausted. Giving up. Status code: {
                      response.status_code}")
                break

            if 'next' not in response.links or single_page:
                break  # Check for a 'next' link to determine if we should continue or if single_page is True
            else:
                url = response.links['next']['url']

        return pages_list

    def search_repos_by_language_and_org(self, language: str, org: str) -> List[Dict]:
        url = f'https://api.github.com/search/repositories?q=org:{
            org}+language:{language}&per_page={MAX_ITEMS_PER_PAGE}'
        pages = self.github_request_exponential_backoff(url)
        all_items = []
        for page in pages:
            if 'items' in page:
                all_items.extend(page['items'])
        return all_items

    def get_most_recent_commit_info(self, repo_full_name: str) -> Dict[str, Any]:
        url = f'https://api.github.com/repos/{repo_full_name}/commits'
        params = {'per_page': 1}
        response = self.github_request_exponential_backoff(
            url, params=params, single_page=True)
        if response is not None and isinstance(response, List) and len(response) > 0:
            commit = response[0][0]     # Just the first commit
            return {
                'most_recent_commit_sha': commit['sha'],
                'most_recent_commit_author': commit['commit']['author']['name'],
                'most_recent_commit_date': commit['commit']['author']['date']
            }
        else:
            return {
                'most_recent_commit_sha': None,
                'most_recent_commit_author': None,
                'most_recent_commit_date': None
            }

    def list_repos(self, repos: List[Dict]) -> pd.DataFrame:
        repo_list = []
        for repo in repos:
            commit_info = self.get_most_recent_commit_info(repo['full_name'])
            repo_info = {
                'name': repo['name'],
                'full_name': repo['full_name'],
                'html_url': repo['html_url'],
                'description': repo['description'],
                'created_at': repo['created_at'],
                'updated_at': repo['updated_at'],
                'pushed_at': repo['pushed_at'],
                'stargazers_count': repo['stargazers_count'],
                'watchers_count': repo['watchers_count'],
                'forks_count': repo['forks_count'],
                'language': repo['language'],
                'owner': repo['owner']['login'],
                'private': repo['private'],
                'size': repo['size'],
                'open_issues_count': repo['open_issues_count'],
                'default_branch': repo['default_branch'],
                **commit_info
            }
            repo_list.append(repo_info)
        return pd.DataFrame(repo_list)

    # Check for dependency files in the repositories
    # The function returns a DataFrame with the dependency management system and the dependency file,
    # for example, 'pip' and 'requirements.txt'
    def check_dependency_files(self, df: pd.DataFrame, dependency_files: Dict[str, str]) -> pd.DataFrame:

        def file_exists_in_repo(repo_full_name: str, file_name: str) -> Tuple[bool, str]:
            def search_directory(repo_full_name: str, path: str) -> Tuple[bool, str]:
                url = f"https://api.github.com/repos/{
                    repo_full_name}/contents/{path}"
                response = self.github_request_exponential_backoff(
                    url, single_page=True)
                if response is not None and isinstance(response, List) and len(response) > 0:
                    for item in response[0]:
                        if item['type'] == 'file' and item['name'] == file_name:
                            return True, item['path']
                        elif item['type'] == 'dir':
                            found, full_path = search_directory(
                                repo_full_name, item['path'])
                            if found:
                                return True, full_path
                return False, ''

            return search_directory(repo_full_name, '')

        def find_dependency_management_system(repo_full_name: str) -> Tuple[str, str]:
            for file_name, system in dependency_files.items():
                found, full_path = file_exists_in_repo(
                    repo_full_name, file_name)
                if found:
                    return system, full_path
            return 'Unknown', 'None'

        df['dependency_management_system'], df['dependency_file'] = zip(
            *df['full_name'].apply(find_dependency_management_system))
        return df


# Initialize the GhsGithub class
github = GhsGithub(GITHUB_TOKEN)

# Search for repositories by language and organization
repos = github.search_repos_by_language_and_org(LANGUAGE, ORGANIZATION)

# List the repositories in a DataFrame
df = github.list_repos(repos)
df.to_csv(f'{ORGANIZATION}_{LANGUAGE}_repos.csv', index=False)

# Check for dependency files
df_with_dependencies = github.check_dependency_files(df, dependency_files)
print(df_with_dependencies)

# Optionally, save the dataframe to a CSV file
df_with_dependencies.to_csv('repos_with_dependencies.csv', index=False)
