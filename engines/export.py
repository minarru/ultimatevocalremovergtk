"""Audio export format conversion."""
import os
import pydub
from bundled.constants import WAV, FLAC, MP3

def save_format(audio_path, save_format, mp3_bit_set, flac_bit_set="16-bit"):
    
    if not save_format == WAV:
        from core.external_tools import configure_pydub_ffmpeg

        configure_pydub_ffmpeg()
        
        musfile = pydub.AudioSegment.from_wav(audio_path)
        
        if save_format == FLAC:
            audio_path_flac = audio_path.replace(".wav", ".flac")
            from core.audio_io import flac_export_parameters

            musfile.export(
                audio_path_flac,
                format="flac",
                parameters=flac_export_parameters(flac_bit_set),
            )
        
        if save_format == MP3:
            audio_path_mp3 = audio_path.replace(".wav", ".mp3")
            try:
                musfile.export(audio_path_mp3, format="mp3", bitrate=mp3_bit_set, codec="libmp3lame")
            except Exception as e:
                print(e)
                musfile.export(audio_path_mp3, format="mp3", bitrate=mp3_bit_set)
        
        try:
            os.remove(audio_path)
        except Exception as e:
            print(e)
