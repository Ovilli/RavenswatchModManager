// FUN_1401a6c20 @ 0x1401a6c20
// purpose-guess: class_alloc_descriptor
// callers (911):
//   FUN_1400c15b0 @ 1400c15b0
//   FUN_140176ef0 @ 140176ef0
//   FUN_140177100 @ 140177100
//   FUN_140177440 @ 140177440
//   FUN_1401772b0 @ 1401772b0
//   FUN_140178040 @ 140178040
//   FUN_140178230 @ 140178230
//   FUN_140178930 @ 140178930
//   FUN_140178740 @ 140178740
//   FUN_140178b20 @ 140178b20
//   FUN_140178ce0 @ 140178ce0
//   FUN_1401795b0 @ 1401795b0
//   FUN_1401797a0 @ 1401797a0
//   FUN_140179ed0 @ 140179ed0
//   FUN_14017a250 @ 14017a250
//   FUN_14017a610 @ 14017a610
//   FUN_140179d10 @ 140179d10
//   FUN_14017a800 @ 14017a800
//   FUN_14017a9f0 @ 14017a9f0
//   FUN_14017abe0 @ 14017abe0
//   FUN_14017add0 @ 14017add0
//   FUN_14017afc0 @ 14017afc0
//   FUN_14017b1b0 @ 14017b1b0
//   FUN_14017b3a0 @ 14017b3a0
//   FUN_14017b590 @ 14017b590
//   FUN_14017b780 @ 14017b780
//   FUN_14017b970 @ 14017b970
//   FUN_14017bb60 @ 14017bb60
//   FUN_14017bd50 @ 14017bd50
//   FUN_14017bf40 @ 14017bf40
//   FUN_14017c130 @ 14017c130
//   FUN_14017cc10 @ 14017cc10
//   FUN_14017ce00 @ 14017ce00
//   FUN_14017cff0 @ 14017cff0
//   FUN_14017d1e0 @ 14017d1e0
//   FUN_14017d3d0 @ 14017d3d0
//   FUN_14017d560 @ 14017d560
//   FUN_14017d730 @ 14017d730
//   FUN_14017d900 @ 14017d900
//   FUN_14017dad0 @ 14017dad0
//   FUN_14017dca0 @ 14017dca0
//   FUN_14017de70 @ 14017de70
//   FUN_14017e040 @ 14017e040
//   FUN_14017e210 @ 14017e210
//   FUN_14017e3b0 @ 14017e3b0
//   FUN_14017e570 @ 14017e570
//   FUN_14017e760 @ 14017e760
//   FUN_14017e950 @ 14017e950
//   FUN_14017eae0 @ 14017eae0
//   FUN_14017ecb0 @ 14017ecb0


undefined8 * FUN_1401a6c20(undefined1 param_1,undefined8 param_2)

{
  undefined8 *puVar1;
  
  LOCK();
  DAT_141415474 = DAT_141415474 + 1;
  UNLOCK();
  puVar1 = (undefined8 *)_malloc_base(0x90);
  if (puVar1 == (undefined8 *)0x0) {
    puVar1 = (undefined8 *)0x0;
  }
  else {
    FUN_1404f2c30(puVar1);
    *puVar1 = oCMetaClass::vftable;
    FUN_1404f4b30(puVar1 + 0x11,param_2,param_1);
  }
  FUN_140c9673c(puVar1);
  return puVar1;
}

