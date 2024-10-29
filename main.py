from datetime import datetime
import aiohttp
import asyncio
from typing import List
from yandex_music import ClientAsync, Sequence, Track
import os
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
import pygame
import tempfile
os.environ['TMPDIR'] = 'C:/mus'

class DescriptionSeed:
    def __init__(self, value: str, tag: str, type: str, **kwargs):
        self.value = value
        self.tag = tag
        self.type = type

    def get_full_name(self, separator=':'):
        return f'{self.type}{separator}{self.tag}'
    
    def get_id_from(self):
        return f'radio-mobile-{self.get_full_name("-")}-default'

class StationSession:
    def __init__(self, radio_session_id: str, batch_id: str, pumpkin: bool, description_seed: dict, accepted_seeds: List[dict], **kwargs):
        self.radio_session_id = radio_session_id
        self.batch_id = batch_id
        self.pumpkin = pumpkin
        self.description_seed = DescriptionSeed(**description_seed)
        self.accepted_seeds = [DescriptionSeed(**seed) for seed in accepted_seeds]

class PlaybackStatistics:
    def __init__(self, total_played_seconds: float, skipped: bool) -> None:
        self.total_played_seconds = total_played_seconds
        self.skipped = skipped

class Station:
    def __init__(self, client: ClientAsync, seeds: str | List[str]):
        self.client = client
        self.seeds = [seeds] if isinstance(seeds, str) else seeds
        self.current_track_number = -1
        self.current_track_id = ''
        self.playback_statistics = None

    def __get_rotor_link(self, path) -> str:
        return f'{self.client.base_url}/rotor/session/{self.session_info.radio_session_id}{path}'

    async def __load_new_sequence(self):
        response = await self.client.request.post(self.__get_rotor_link('/tracks'), json={
            "queue": [self.sequence[0].track.id]
        })
        self.sequence = Sequence.de_list(response['sequence'], self.client)
        print("Новая последовательность треков загружена.")

    def __get_current_timestamp(self) -> str:
        return datetime.now().astimezone().strftime('%Y-%m-%dT%H:%M:%S.%f%z')

    async def __send_feedback(self, type: str, **kwargs):
        await self.client.request.post(self.__get_rotor_link('/feedback'), json={
            'event': {
                'type': type,
                'timestamp': self.__get_current_timestamp(),
                **kwargs
            },
            'batchId': self.session_info.batch_id
        })

    async def new_session(self):
        response = await self.client.request.post(f'{self.client.base_url}/rotor/session/new', json={
            'seeds': self.seeds,
            'includeTracksInResponse': True
        })
        self.session_info = StationSession(**response)
        self.sequence = Sequence.de_list(response['sequence'], self.client)
        await self.__send_feedback('radioStarted', **{
            'from': self.session_info.description_seed.get_id_from()
        })
        print("Играет: Моя волна")

    def set_playback_statistics(self, playback_statistics: PlaybackStatistics):
        self.playback_statistics = playback_statistics

    def __get_current_track(self) -> Track | None:
        return self.sequence[self.current_track_number].track if 0 <= self.current_track_number < len(self.sequence) else None

    async def next_track(self) -> Track:
        if self.current_track_number != -1:
            await self.__send_feedback('skip' if self.playback_statistics.skipped else 'trackFinished', **{
                'trackId': self.current_track_id,
                'totalPlayedSeconds': self.playback_statistics.total_played_seconds if self.playback_statistics.skipped else 0.1
            })

        self.current_track_number += 1
        track = self.__get_current_track()
        if track is None:
            self.current_track_number = 0
            await self.__load_new_sequence()
            track = self.__get_current_track()

        self.current_track_id = track.id
        await self.__send_feedback('trackStarted', **{
            'trackId': self.current_track_id,
        })
        return track

    async def download_and_play_track(self, track: Track):
     download_info = await self.client.tracks_download_info(track.id, get_direct_links=True)
     download_url = download_info[0].direct_link
     temp_file_path = None
    
     for attempt in range(3):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(download_url) as response:
                    if response.status == 200:
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_file:
                            temp_file.write(await response.read())
                            temp_file_path = temp_file.name

                        # Перезапуск pygame и воспроизведение
                        pygame.mixer.quit()
                        pygame.mixer.init()
                        pygame.mixer.music.load(temp_file_path)
                        pygame.mixer.music.play()

                        try:
                            while pygame.mixer.music.get_busy():
                                await asyncio.sleep(1)
                        except Exception as e:
                            print(f"Ошибка во время воспроизведения: {e}")
                        
                        await asyncio.sleep(0.1)
                        break  # Успешное воспроизведение завершено, выходим из цикла
                    else:
                        print(f"Не удалось загрузить трек: {response.status}")
                        return 0
        except pygame.error as e:
            print(f"Ошибка декодирования: {e}. Повторная попытка {attempt + 1} из 3.")
            await asyncio.sleep(1)
        
        finally:
            # Попытка удалить временный файл
            if temp_file_path:
                try:
                    os.remove(temp_file_path)
                except OSError as e:
                    print(f"Ошибка при удалении временного файла: {e}")
    
     return pygame.mixer.music.get_pos() / 1000 if pygame.mixer.music.get_busy() else 0

async def main():
    #Ваш токен Яндекс Музыки
    token = ""
    client = ClientAsync(token)
    await client.init()
    station = Station(client, "user:onyourwave")
    await station.new_session()
    while True:
        track = await station.next_track()
        print(f'Сейчас играет: {", ".join([artist.name for artist in track.artists])} - {track.title}')
        duration = await station.download_and_play_track(track)
        
        # Задаем статистику после завершения трека
        station.set_playback_statistics(PlaybackStatistics(
            total_played_seconds=duration,
            skipped=False
        ))
        await asyncio.sleep(duration)

if __name__ == "__main__":
    asyncio.run(main())